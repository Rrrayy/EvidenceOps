import json

from threading import Barrier,Event

import pytest

from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.llm_gateway import LLMGateway
from evidenceops.application.model_protocol import FinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.tool_runtime import ToolRuntime,ToolSpec
from evidenceops.infrastructure.providers.mock_provider import MockProvider


def test_batch_executes_concurrently_and_correlates_history()->None:
	barrier=Barrier(3)
	third_finished=Event()
	completion_order=[]
	requests=[]
	def handler(arguments):
		# 若串行执行，第一个handler会等待超时；三个必须同时到达。
		barrier.wait(timeout=2)
		if arguments["value"]==0:
			assert third_finished.wait(timeout=2)
		completion_order.append(arguments["value"])
		if arguments["value"]==2:
			third_finished.set()
		return {"value":arguments["value"]}
	tool=ToolSpec("query",True,lambda arguments:arguments,handler)
	runtime=ToolRuntime((tool,),timeout_seconds=3)
	calls=tuple(ToolCall(f"call-{index}","query",{"value":index}) for index in range(3))
	def answer(request):
		requests.append(request)
		return FinalAnswer("查询完成")
	loop=AgentLoop(LLMGateway(MockProvider((ToolCallBatch(calls),answer)),"mock"),runtime,max_steps=2)
	try:
		result=loop.run("并发查询",run_id="run-parallel")
	finally:
		runtime.close()
	assert result.error_code is None
	assert completion_order.index(2)<completion_order.index(0)
	records=[record for record in result.execution_records if record.kind=="tool"]
	assert len(records)==3
	assert max(record.handler_started_at for record in records)<min(record.handler_finished_at for record in records)
	assert all(record.run_id=="run-parallel" and record.model_round==1 for record in records)
	assert [record.model_round for record in result.execution_records if record.kind=="model"]==[1,2]
	assert [item.data["value"] for item in result.tool_results]==[0,1,2]
	assert [item.evidence_id for item in result.tool_results]==[f"run-parallel-call-{index}" for index in range(3)]
	history=requests[0].messages
	assistant=[message for message in history if message["role"]=="assistant"]
	assert len(assistant)==1
	assert [call["id"] for call in assistant[0]["tool_calls"]]==[call.tool_call_id for call in calls]
	results=[message for message in history if message["role"]=="tool"]
	assert [message["tool_call_id"] for message in results]==[call.tool_call_id for call in calls]
	assert [json.loads(message["content"])["data"]["value"] for message in results]==[0,1,2]


def test_batch_preserves_success_validation_error_and_timeout()->None:
	release=Event()
	started=Event()
	finished=Event()
	def slow(arguments):
		started.set()
		try:
			release.wait(timeout=2)
			return "late"
		finally:
			finished.set()
	def validate(arguments):
		raise ValueError("参数不合法")
	runtime=ToolRuntime((
		ToolSpec("good",True,lambda arguments:arguments,lambda arguments:"ok"),
		ToolSpec("invalid",True,validate,lambda arguments:pytest.fail("不应执行非法参数")),
		ToolSpec("slow",True,lambda arguments:arguments,slow),
	),timeout_seconds=0.1)
	calls=tuple(ToolCall(f"call-{name}",name,{}) for name in ("good","invalid","slow"))
	loop=AgentLoop(LLMGateway(MockProvider((ToolCallBatch(calls),)),"mock"),runtime)
	try:
		result=loop.run("查询",run_id="run-mixed")
		assert started.is_set()
		assert not finished.is_set()
		assert result.final_answer is None
		assert result.error_code=="INVALID_ARGUMENTS"
		assert [item.error_code for item in result.tool_results]==[None,"INVALID_ARGUMENTS","TOOL_TIMEOUT"]
		assert result.tool_results[0].evidence_id=="run-mixed-call-good"
		assert result.tool_results[1].execution_record.handler_started_at is None
		assert result.tool_results[2].execution_record.handler_started_at is not None
		assert result.tool_results[2].execution_record.handler_finished_at is None
		assert all(item.data is None and item.evidence_id is None for item in result.tool_results[1:])
	finally:
		release.set()
		assert finished.wait(timeout=2)
		runtime.close()


def test_duplicate_call_across_rounds_is_rejected_before_execution()->None:
	executions=[]
	runtime=ToolRuntime((ToolSpec("query",True,lambda arguments:arguments,lambda arguments:executions.append(1)),))
	call=ToolCall("same-id","query",{})
	loop=AgentLoop(LLMGateway(MockProvider((call,call)),"mock"),runtime)
	try:
		result=loop.run("查询")
	finally:
		runtime.close()
	assert result.error_code=="MODEL_PROTOCOL_ERROR"
	assert executions==[1]


@pytest.mark.parametrize("calls",[(),(ToolCall("same","query",{}),)*2,tuple(ToolCall(str(index),"query",{}) for index in range(17))])
def test_invalid_batches_are_rejected(calls)->None:
	with pytest.raises(ValueError):
		ToolCallBatch(calls)
