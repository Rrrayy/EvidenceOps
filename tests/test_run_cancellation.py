import asyncio
import json
import socket
from io import StringIO
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier,Event,Lock,Thread

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ModelRequest,ProviderResponse,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.run_budget import RunBudget,RunBudgetExceeded
from evidenceops.application.run_control import RunCancelled,RunControl
from evidenceops.application.run_repository import RunPersistenceError
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.connectors.local_config import build_local_config_tool
from evidenceops.connectors.local_log import build_local_log_tool
from evidenceops.connectors.local_metric import build_local_metric_tool
from evidenceops.connectors import local_config,local_log,local_metric
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.models import Base
from evidenceops.infrastructure.providers.openai_compatible_provider import OpenAICompatibleProvider
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def final_answer(request):
	ids=[json.loads(message["content"])["evidence_id"] for message in request.messages if message["role"]=="tool"]
	return StructuredFinalAnswer({"root_cause":{"text":"相关性待核实","evidence_ids":ids},
		"recommendations":[{"text":"补查调用链","evidence_ids":ids}],"confidence":0.5,"limitations":"仅有样本"})


class WaitingProvider:
	def __init__(self,wait_round=1):
		self.wait_round=wait_round
		self.started=Event()
		self.release=Event()
		self.requests=[]

	def complete(self,request):
		self.requests.append(request)
		if len(self.requests)==self.wait_round:
			self.started.set()
			# 信号已到后仍保持等待点，让测试能确定性发送重复取消。
			assert request.control.wait(3)
			assert self.release.wait(3)
			request.control.check()
		window={"service_name":"order-service","environment":"production",
			"start_time":"2026-10-05T10:00:00+08:00","end_time":"2026-10-05T10:10:00+08:00","limit":50}
		response=ToolCallBatch((ToolCall("log","query_service_logs",dict(window,error_type="rpc_timeout")),
			ToolCall("metric","query_service_metrics",window),ToolCall("config","query_service_config",
				{"service_name":"order-service","environment":"production","at_time":"2026-10-05T10:02:00+08:00"})))
		return ProviderResponse(response,request.model,None)


def database_persistence():
	engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
	Base.metadata.create_all(engine)
	return SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)


@pytest.mark.parametrize("wait_round,evidence_count",[(1,0),(2,3)])
def test_api_cancel_is_idempotent_and_persisted_with_evidence(wait_round,evidence_count):
	provider=WaitingProvider(wait_round)
	assembly=build_agent_diagnosis_assembly(provider,"test",
		(build_local_log_tool(),build_local_metric_tool(),build_local_config_tool()),"order-service",
		diagnosis_persistence=database_persistence())
	with TestClient(create_app(assembly)) as client,ThreadPoolExecutor(max_workers=1) as worker:
		future=worker.submit(client.post,"/api/v1/agent/diagnosis/stream",json={"description":"取消验收"})
		try:
			assert provider.started.wait(2)
			run_id=provider.requests[-1].run_id
			first=client.post(f"/api/v1/agent/runs/{run_id}/cancel")
			second=client.post(f"/api/v1/agent/runs/{run_id}/cancel")
			assert first.status_code==second.status_code==202
			assert not first.json()["already_requested"] and second.json()["already_requested"]
			assert client.get(f"/api/v1/agent/runs/{run_id}").json()["status"]=="running"
		finally:
			provider.release.set()
		stream=future.result(timeout=4)
		events=[json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
		assert [item["event"] for item in events].count("run_cancel_requested")==1
		assert events[-1]["event"]=="run_cancelled"
		assert not any(item["event"] in ("run_completed","run_failed") for item in events)
		for body in (events[-1]["data"]["result"],client.get(f"/api/v1/agent/runs/{run_id}").json()):
			assert body["status"]=="cancelled" and body["report"] is None
			assert body["error_code"] is None
			assert len(body["evidences"])==evidence_count
			assert len(body["execution_records"])==(1 if wait_round==1 else 5)
			assert body["execution_records"][-1]["status"]=="cancelled"
			assert body["execution_records"][-1]["error_code"]=="RUN_CANCELLED"
		assert client.post(f"/api/v1/agent/runs/{run_id}/cancel").status_code==200
		assert assembly.diagnosis_service._registry.get(run_id) is None


def test_unknown_and_orphaned_running_runs_are_not_fake_cancelled():
	persistence=database_persistence()
	run=DiagnosisRun("run-orphan","req-orphan","重启遗留")
	run.transition(RunStatus.RUNNING)
	with persistence.transaction() as transaction:
		transaction.run.create(run)
	assembly=build_agent_diagnosis_assembly(WaitingProvider(),"test",(build_thread_pool_tool(),),"order-service",
		diagnosis_persistence=persistence)
	with TestClient(create_app(assembly)) as client:
		assert client.post("/api/v1/agent/runs/missing/cancel").status_code==404
		assert client.post("/api/v1/agent/runs/run-orphan/cancel").status_code==409
		assert client.get("/api/v1/agent/runs/run-orphan").json()["status"]=="running"


def test_terminal_claim_and_cancel_have_one_winner():
	# 同一锁下的认领点决定先后，不能同时承诺接纳取消和提交成功。
	for attempt in range(40):
		control=RunControl()
		barrier=Barrier(2)
		def cancel():
			barrier.wait(2)
			return control.request_cancel()
		def finish():
			barrier.wait(2)
			return control.claim_terminal(RunStatus.SUCCEEDED)
		with ThreadPoolExecutor(max_workers=2) as worker:
			cancellation=worker.submit(cancel)
			completion=worker.submit(finish)
			decision=cancellation.result(3)
			status=completion.result(3)
		assert decision["cancellation_requested"]==(status is RunStatus.CANCELLED)
		assert control.claim_terminal(RunStatus.FAILED) is status


@pytest.mark.parametrize("cooperative",[False,True])
def test_running_tool_cancellation_does_not_claim_thread_is_killed(cooperative):
	control=RunControl()
	started=Event()
	release=Event()
	finished=Event()
	spec=build_thread_pool_tool()
	def handler(arguments):
		started.set()
		try:
			assert release.wait(3)
			return spec.handler(arguments)
		finally:
			finished.set()
	def controlled_handler(arguments,run_control):
		started.set()
		try:
			assert run_control.wait(3)
			run_control.check()
		finally:
			finished.set()
	runtime=ToolRuntime((replace(spec,handler=handler,controlled_handler=controlled_handler if cooperative else None),),3)
	with ThreadPoolExecutor(max_workers=1) as worker:
		future=worker.submit(runtime.execute,spec.name,{"service_name":"order-service"},control=control)
		try:
			assert started.wait(1)
			control.request_cancel()
			result=future.result(1)
			assert result.error_code=="RUN_CANCELLED" and result.execution_record.status=="cancelled"
			if cooperative:
				assert finished.wait(1)
			else:
				assert not finished.is_set()
		finally:
			release.set()
			assert finished.wait(1)
			runtime.close()


def test_cancelled_queued_handler_never_starts(monkeypatch):
	control=RunControl()
	release=Event()
	started=[]
	spec=build_thread_pool_tool()
	runtime=ToolRuntime((replace(spec,handler=lambda arguments:started.append(arguments)),),3)
	# 占满handler线程，确保被测任务只能排队。
	blockers=[runtime._executor.submit(release.wait,3) for number in range(4)]
	queued=Event()
	submit=runtime._executor.submit
	def mark_submission(*args,**kwargs):
		future=submit(*args,**kwargs)
		queued.set()
		return future
	monkeypatch.setattr(runtime._executor,"submit",mark_submission)
	with ThreadPoolExecutor(max_workers=1) as worker:
		try:
			future=worker.submit(runtime.execute,spec.name,{"service_name":"order-service"},control=control)
			assert queued.wait(1)
			control.request_cancel()
			result=future.result(1)
			assert result.error_code=="RUN_CANCELLED" and not started
			assert result.execution_record.handler_started_at is None
		finally:
			release.set()
			for blocker in blockers:
				blocker.result(1)
			runtime.close()


@pytest.mark.parametrize("stop_reason",["cancel","budget"])
def test_async_model_transport_is_cleaned_up(stop_reason):
	control=RunControl()
	started=Event()
	cleaned=Event()
	async def handler(request):
		started.set()
		try:
			await asyncio.Event().wait()
		finally:
			cleaned.set()
	provider=OpenAICompatibleProvider("https://model.test/v1","test-key",
		async_client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler)))
	request=ModelRequest(({"role":"user","content":"诊断"},),(),"test",120,"req-http","run-http",
		control=control,budget=RunBudget(0.15) if stop_reason=="budget" else None)
	with ThreadPoolExecutor(max_workers=1) as worker:
		try:
			future=worker.submit(provider.complete,request)
			assert started.wait(1)
			if stop_reason=="cancel":
				control.request_cancel()
			with pytest.raises(RunCancelled if stop_reason=="cancel" else RunBudgetExceeded):
				future.result(2)
			assert cleaned.is_set()
		finally:
			control.request_cancel()
			provider.close()


def test_late_synchronous_provider_result_cannot_start_tools():
	class LateProvider:
		def complete(self,request):
			request.control.request_cancel()
			return ProviderResponse(ToolCall("late","query_thread_pool_snapshot",{"service_name":"order-service"}),"test",None)
	assembly=build_agent_diagnosis_assembly(LateProvider(),"test",(build_thread_pool_tool(),),"order-service")
	try:
		result=assembly.diagnosis_service.execute("req-late","取消后的迟到结果")
		assert result.run.status is RunStatus.CANCELLED and not result.evidences and result.report is None
		assert len(result.execution_records)==1
	finally:
		assembly.close()


def test_cancelling_real_http_read_closes_local_connection():
	control=RunControl()
	started=Event()
	closed=Event()
	errors=[]
	listener=socket.socket()
	listener.bind(("127.0.0.1",0))
	listener.listen(1)
	listener.settimeout(3)
	port=listener.getsockname()[1]
	def serve():
		try:
			with listener.accept()[0] as connection:
				connection.settimeout(3)
				received=b""
				while b"\r\n\r\n" not in received:
					received+=connection.recv(4096)
				# 声明尚未发送完的响应，使客户端停在真实TCP读取等待中。
				connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{")
				started.set()
				while connection.recv(4096):
					pass
				closed.set()
		except ConnectionResetError:
			closed.set()
		except Exception as error:
			errors.append(error)
	thread=Thread(target=serve,daemon=True)
	thread.start()
	provider=OpenAICompatibleProvider(f"http://127.0.0.1:{port}/v1","test-key",
		async_client_factory=lambda:httpx.AsyncClient(trust_env=False))
	request=ModelRequest(({"role":"user","content":"测试"},),(),"test",120,"req-tcp","run-tcp",control=control)
	try:
		with ThreadPoolExecutor(max_workers=1) as worker:
			future=worker.submit(provider.complete,request)
			assert started.wait(2)
			control.request_cancel()
			with pytest.raises(RunCancelled):
				future.result(2)
			assert closed.wait(2)
		thread.join(1)
		assert not thread.is_alive() and not errors
	finally:
		control.request_cancel()
		provider.close()
		listener.close()


def test_success_claim_rejects_cancel_during_database_commit(monkeypatch):
	class Provider:
		def complete(self,request):
			response=final_answer(request) if any(message["role"]=="tool" for message in request.messages) else (
				ToolCall("snapshot","query_thread_pool_snapshot",{"service_name":"order-service"}))
			return ProviderResponse(response,"test",None)
	assembly=build_agent_diagnosis_assembly(Provider(),"test",(build_thread_pool_tool(),),"order-service",
		diagnosis_persistence=database_persistence())
	entered=Event()
	release=Event()
	ids=[]
	persist=assembly.diagnosis_service._persist_success
	def delayed_commit(run,*args):
		ids.append(run.run_id)
		entered.set()
		assert release.wait(3)
		persist(run,*args)
	monkeypatch.setattr(assembly.diagnosis_service,"_persist_success",delayed_commit)
	try:
		with TestClient(create_app(assembly)) as client,ThreadPoolExecutor(max_workers=1) as worker:
			future=worker.submit(client.post,"/api/v1/agent/diagnosis/stream",json={"description":"提交竞争"})
			try:
				assert entered.wait(2)
				decision=client.post(f"/api/v1/agent/runs/{ids[0]}/cancel")
				assert decision.status_code==409 and not decision.json()["cancellation_requested"]
				assert decision.json()["phase"]=="finalizing"
			finally:
				release.set()
			assert "event: run_completed" in future.result(3).text
			assert client.get(f"/api/v1/agent/runs/{ids[0]}").json()["status"]=="succeeded"
	finally:
		release.set()


def test_cancel_save_failure_never_claims_durable_cancellation(monkeypatch):
	provider=WaitingProvider()
	assembly=build_agent_diagnosis_assembly(provider,"test",(build_thread_pool_tool(),),"order-service")
	def broken_save(run,*args):
		raise RunPersistenceError("fail",run.run_id)
	monkeypatch.setattr(assembly.diagnosis_service,"_persist_failure",broken_save)
	try:
		with TestClient(create_app(assembly)) as client,ThreadPoolExecutor(max_workers=1) as worker:
			future=worker.submit(client.post,"/api/v1/agent/diagnosis/stream",json={"description":"取消保存失败"})
			try:
				assert provider.started.wait(2)
				assert client.post(f"/api/v1/agent/runs/{provider.requests[0].run_id}/cancel").status_code==202
			finally:
				provider.release.set()
			stream=future.result(3).text
			assert "PERSISTENCE_FAILED" in stream
			assert "event: run_cancelled" not in stream
	finally:
		provider.release.set()


def test_cancel_signal_is_isolated_between_concurrent_runs():
	class Provider:
		def __init__(self):
			self.lock=Lock()
			self.requests={}
			self.started=Event()
			self.release=Event()
		def complete(self,request):
			if not any(message["role"]=="tool" for message in request.messages):
				return ProviderResponse(ToolCall("snapshot","query_thread_pool_snapshot",{"service_name":"order-service"}),"test",None)
			prompt=next(message["content"] for message in request.messages if message["role"]=="user")
			with self.lock:
				self.requests[prompt]=request
				if len(self.requests)==2:
					self.started.set()
			while not self.release.wait(0.02):
				request.control.check()
			return ProviderResponse(final_answer(request),"test",None)
	provider=Provider()
	assembly=build_agent_diagnosis_assembly(provider,"test",(build_thread_pool_tool(),),"order-service")
	try:
		with ThreadPoolExecutor(max_workers=2) as worker:
			cancelled=worker.submit(assembly.diagnosis_service.execute,"req-a","诊断A")
			completed=worker.submit(assembly.diagnosis_service.execute,"req-b","诊断B")
			try:
				assert provider.started.wait(2)
				assembly.diagnosis_service.request_cancel(provider.requests["诊断A"].run_id)
				assert cancelled.result(2).run.status is RunStatus.CANCELLED
			finally:
				provider.release.set()
			assert completed.result(2).run.status is RunStatus.SUCCEEDED
	finally:
		provider.release.set()
		assembly.close()


@pytest.mark.parametrize("module,registry_name,builder",[
	(local_log,"SERVICE_REGISTRY",build_local_log_tool),
	(local_metric,"METRIC_REGISTRY",build_local_metric_tool),
	(local_config,"CONFIG_REGISTRY",build_local_config_tool),
])
def test_connector_cancellation_closes_file_between_rows(monkeypatch,module,registry_name,builder):
	control=RunControl()
	registry=getattr(module,registry_name)
	source=registry[("order-service","production")]
	class SourceFile(StringIO):
		def __next__(self):
			line=super().__next__()
			control.request_cancel()
			return line
	file=SourceFile(source.source_path.read_text(encoding="utf-8"))
	class SourcePath:
		def exists(self):
			return True
		def open(self,**kwargs):
			return file
	monkeypatch.setitem(registry,("order-service","production"),replace(source,source_path=SourcePath()))
	arguments={"service_name":"order-service","environment":"production"}
	if module is local_config:
		arguments["at_time"]="2026-10-05T10:02:00+08:00"
	else:
		arguments.update(start_time="2026-10-05T10:00:00+08:00",end_time="2026-10-05T10:10:00+08:00",limit=50)
		if module is local_log:
			arguments["error_type"]="rpc_timeout"
	spec=builder()
	with pytest.raises(RunCancelled):
		spec.controlled_handler(spec.validate_arguments(arguments),control)
	assert file.closed


def test_cancellation_before_success_claim_discards_report_but_preserves_evidence(monkeypatch):
	class Provider:
		def complete(self,request):
			response=final_answer(request) if any(message["role"]=="tool" for message in request.messages) else (
				ToolCall("snapshot","query_thread_pool_snapshot",{"service_name":"order-service"}))
			return ProviderResponse(response,"test",None)
	assembly=build_agent_diagnosis_assembly(Provider(),"test",(build_thread_pool_tool(),),"order-service")
	generator=assembly.diagnosis_service._report_generator
	generate=type(generator).generate
	def cancel_after_generate(self,run,*args):
		report=generate(self,run,*args)
		assembly.diagnosis_service.request_cancel(run.run_id)
		return report
	monkeypatch.setattr(type(generator),"generate",cancel_after_generate)
	try:
		result=assembly.diagnosis_service.execute("req-commit-cancel","取消优先")
		assert result.run.status is RunStatus.CANCELLED and result.report is None
		assert len(result.evidences)==1
	finally:
		assembly.close()


def test_budget_expiry_stops_cooperative_handler_without_user_cancel():
	control=RunControl(budget=RunBudget(0.1))
	finished=Event()
	spec=build_thread_pool_tool()
	def handler(arguments,run_control):
		try:
			run_control.wait(3)
			run_control.check()
		finally:
			finished.set()
	runtime=ToolRuntime((replace(spec,controlled_handler=handler),),3)
	try:
		result=runtime.execute(spec.name,{"service_name":"order-service"},control=control)
		assert result.error_code=="RUN_TIMEOUT"
		assert finished.wait(1)
	finally:
		runtime.close()


def test_shared_provider_cancel_does_not_close_other_run_request():
	first_control=RunControl()
	second_control=RunControl()
	first_started=Event()
	second_started=Event()
	first_cleaned=Event()
	release=Event()
	async def handler(request):
		payload=json.loads(request.content)
		assert "control" not in payload and "budget" not in payload
		if request.headers["X-Run-ID"]=="run-a":
			first_started.set()
			try:
				await asyncio.Event().wait()
			finally:
				first_cleaned.set()
		second_started.set()
		while not release.is_set():
			await asyncio.sleep(0.01)
		return httpx.Response(200,json={"choices":[{"message":{"content":"正常回答"}}]})
	provider=OpenAICompatibleProvider("https://model.test/v1","test-key",
		async_client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler)))
	def request(run_id,control):
		return ModelRequest(({"role":"user","content":"测试"},),(),"test",120,f"req-{run_id}",run_id,control=control)
	try:
		with ThreadPoolExecutor(max_workers=2) as worker:
			first=worker.submit(provider.complete,request("run-a",first_control))
			second=worker.submit(provider.complete,request("run-b",second_control))
			try:
				assert first_started.wait(1) and second_started.wait(1)
				first_control.request_cancel()
				with pytest.raises(RunCancelled):
					first.result(2)
				assert first_cleaned.is_set() and not second.done()
			finally:
				first_control.request_cancel()
				release.set()
			assert second.result(2).response.text=="正常回答"
	finally:
		provider.close()


def test_explicit_sync_client_injection_is_not_bypassed():
	client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,
		json={"choices":[{"message":{"content":"注入客户端回答"}}]})))
	provider=OpenAICompatibleProvider("https://never-contact.test/v1","test-key",client=client)
	request=ModelRequest(({"role":"user","content":"测试"},),(),"test",120,"req-injected","run-injected",control=RunControl())
	try:
		assert provider.complete(request).response.text=="注入客户端回答"
	finally:
		provider.close()


def test_event_callback_can_request_cancel_without_deadlock():
	class Provider:
		def complete(self,request):
			request.control.check()
			return ProviderResponse(final_answer(request),"test",None)
	assembly=build_agent_diagnosis_assembly(Provider(),"test",(build_thread_pool_tool(),),"order-service")
	events=[]
	def sink(event):
		events.append(event)
		if event["event"] in ("model_started","run_cancel_requested"):
			assembly.diagnosis_service.request_cancel(event["run_id"])
	try:
		result=assembly.diagnosis_service.execute("req-callback","回调取消",sink)
		assert result.run.status is RunStatus.CANCELLED
		assert sum(event["event"]=="run_cancel_requested" for event in events)==1
		assert events[-1]["event"]=="run_cancelled"
	finally:
		assembly.close()
