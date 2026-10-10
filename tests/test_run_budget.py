import json
from dataclasses import replace
from threading import Event

import pytest

from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ModelProviderError,ProviderResponse,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.run_budget import RunBudget,RunBudgetExceeded
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.mocks.thread_pool import build_thread_pool_tool


class Clock:
	def __init__(self):
		self.value=0

	def __call__(self):
		return self.value


class BudgetProvider:
	def __init__(self,clock,costs,failure=False):
		self.clock=clock
		self.costs=iter(costs)
		self.requests=[]
		self.failure=failure

	def complete(self,request):
		self.requests.append(request)
		self.clock.value+=next(self.costs)
		if self.failure:
			raise ModelProviderError("MODEL_TIMEOUT","单次模型超时")
		observations=[json.loads(message["content"]) for message in request.messages if message["role"]=="tool"]
		if not observations:
			response=ToolCall("call-budget","query_thread_pool_snapshot",{"service_name":"order-service"})
		else:
			ids=[item["evidence_id"] for item in observations]
			response=StructuredFinalAnswer({"root_cause":{"text":"线程池满载","evidence_ids":ids},
				"recommendations":[{"text":"补查调用链","evidence_ids":ids}],"confidence":0.5,"limitations":"仅有快照"})
		return ProviderResponse(response,"budget-model",None)

	def close(self):
		pass


@pytest.mark.parametrize("value",[0,-1,float("nan"),float("inf"),True,"10"])
def test_invalid_budget_is_rejected(value):
	with pytest.raises(ValueError):
		RunBudget(value)


def test_shared_deadline_and_exact_boundary():
	clock=Clock()
	budget=RunBudget(10,clock)
	assert budget.limit(120)==10
	clock.value=4
	assert budget.limit(120)==6
	clock.value=10
	with pytest.raises(RunBudgetExceeded):
		budget.check()


def test_rounds_and_tools_consume_same_budget():
	clock=Clock()
	provider=BudgetProvider(clock,[4,1])
	spec=build_thread_pool_tool()
	def handler(arguments):
		clock.value+=2
		return spec.handler(arguments)
	assembly=build_agent_diagnosis_assembly(provider,"test",(replace(spec,handler=handler),),"order-service",
		model_timeout_seconds=120,max_steps=3)
	try:
		result=assembly.evidence_collector._agent_loop.run("诊断",budget=RunBudget(10,clock))
	finally:
		assembly.close()
	assert result.error_code is None
	assert [request.timeout_seconds for request in provider.requests]==[10,4]


def test_late_model_response_cannot_start_tool_or_be_success():
	clock=Clock()
	provider=BudgetProvider(clock,[11])
	assembly=build_agent_diagnosis_assembly(provider,"test",(build_thread_pool_tool(),),"order-service")
	try:
		result=assembly.evidence_collector._agent_loop.run("诊断",budget=RunBudget(10,clock))
	finally:
		assembly.close()
	assert result.error_code=="RUN_TIMEOUT"
	assert result.final_answer is None and not result.tool_results
	assert len(result.execution_records)==1
	assert result.execution_records[0].error_code=="RUN_TIMEOUT"


def test_expired_tool_stops_next_model_round():
	clock=Clock()
	provider=BudgetProvider(clock,[4])
	spec=build_thread_pool_tool()
	def handler(arguments):
		clock.value=10
		return spec.handler(arguments)
	assembly=build_agent_diagnosis_assembly(provider,"test",(replace(spec,handler=handler),),"order-service")
	try:
		result=assembly.evidence_collector._agent_loop.run("诊断",budget=RunBudget(10,clock))
	finally:
		assembly.close()
	assert result.error_code=="RUN_TIMEOUT"
	assert len(provider.requests)==1
	assert result.execution_records[-1].error_code=="RUN_TIMEOUT"


def test_expired_batch_never_starts_handlers():
	clock=Clock()
	budget=RunBudget(10,clock)
	clock.value=10
	spec=build_thread_pool_tool()
	started=[]
	runtime=ToolRuntime((replace(spec,handler=lambda args:started.append(args)),))
	try:
		results=runtime.execute_many(tuple(ToolCall(f"call-{number}",spec.name,{"service_name":"order-service"})
			for number in range(6)),budget=budget)
	finally:
		runtime.close()
	assert not started
	assert all(item.error_code=="RUN_TIMEOUT" for item in results)
	assert all(item.execution_record.handler_started_at is None for item in results)


@pytest.mark.parametrize("cost,expected",[(2,"MODEL_TIMEOUT"),(10,"RUN_TIMEOUT")])
def test_model_timeout_and_run_timeout_are_distinct(cost,expected):
	clock=Clock()
	provider=BudgetProvider(clock,[cost],failure=True)
	assembly=build_agent_diagnosis_assembly(provider,"test",(build_thread_pool_tool(),),"order-service")
	try:
		result=assembly.evidence_collector._agent_loop.run("诊断",budget=RunBudget(10,clock))
	finally:
		assembly.close()
	assert result.error_code==expected


def test_real_tool_wait_is_limited_without_claiming_thread_cancellation():
	gate=Event()
	started=Event()
	finished=Event()
	spec=build_thread_pool_tool()
	def handler(arguments):
		started.set()
		gate.wait(2)
		finished.set()
		return spec.handler(arguments)
	runtime=ToolRuntime((replace(spec,handler=handler),),timeout_seconds=1)
	try:
		result=runtime.execute(spec.name,{"service_name":"order-service"},budget=RunBudget(0.1))
		assert started.is_set() and not finished.is_set()
		assert result.error_code=="RUN_TIMEOUT"
	finally:
		gate.set()
		assert finished.wait(1)
		runtime.close()


def test_service_persists_timeout_and_emits_one_failure(monkeypatch):
	clock=Clock()
	monkeypatch.setattr("evidenceops.application.diagnosis_service.RunBudget",lambda seconds:RunBudget(seconds,clock))
	assembly=build_agent_diagnosis_assembly(BudgetProvider(clock,[11]),"test",(build_thread_pool_tool(),),
		"order-service",run_timeout_seconds=10)
	saved=[]
	assembly.diagnosis_service._persist_failure=lambda run,evidences,records:saved.append((run.status.value,run.error_code,records))
	events=[]
	try:
		result=assembly.diagnosis_service.execute("budget-test","诊断",events.append)
	finally:
		assembly.close()
	assert result.run.error_code=="RUN_TIMEOUT" and result.report is None
	assert saved[0][0:2]==("failed","RUN_TIMEOUT")
	assert len(saved[0][2])==1
	assert events[-1]["event"]=="run_failed"
	assert events[-1]["data"]["result"]["error_code"]=="RUN_TIMEOUT"
	assert not any(item["event"]=="run_completed" for item in events)


def test_late_final_answer_is_rejected():
	clock=Clock()
	provider=BudgetProvider(clock,[4,7])
	assembly=build_agent_diagnosis_assembly(provider,"test",(build_thread_pool_tool(),),"order-service")
	try:
		result=assembly.evidence_collector._agent_loop.run("诊断",budget=RunBudget(10,clock))
	finally:
		assembly.close()
	assert result.error_code=="RUN_TIMEOUT" and result.final_answer is None
	assert len(result.tool_results)==1
	assert result.execution_records[-1].error_code=="RUN_TIMEOUT"


@pytest.mark.parametrize("stage",["setup","report"])
def test_service_checks_budget_after_synchronous_work(monkeypatch,stage):
	clock=Clock()
	monkeypatch.setattr("evidenceops.application.diagnosis_service.RunBudget",lambda seconds:RunBudget(seconds,clock))
	provider=BudgetProvider(clock,[1,1])
	assembly=build_agent_diagnosis_assembly(provider,"test",(build_thread_pool_tool(),),"order-service",run_timeout_seconds=10)
	service=assembly.diagnosis_service
	if stage=="setup":
		service._persist_create=lambda run:setattr(clock,"value",10)
	else:
		generate=service._report_generator.generate
		def late_report(*args):
			clock.value=10
			return generate(*args)
		monkeypatch.setattr(type(service._report_generator),"generate",lambda self,*args:late_report(*args))
	try:
		result=service.execute("budget-stage","诊断")
	finally:
		assembly.close()
	assert result.run.error_code=="RUN_TIMEOUT" and result.report is None
	assert len(provider.requests)==(0 if stage=="setup" else 2)
