import asyncio
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Barrier,Event,Thread
from time import monotonic,sleep

import pytest
import httpx
import uvicorn
from fastapi.testclient import TestClient

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.api.diagnosis_stream import DiagnosisStreamRunner,EventChannel,StreamBusyError,encode_event
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ModelProviderError,ProviderResponse,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.run_events import RunEvents
from evidenceops.application.run_repository import RunPersistenceError
from evidenceops.mocks.thread_pool import build_thread_pool_tool


class TestProvider:
	__test__=False

	def __init__(self,gate:Event|None=None,failure:str|None=None,batch:bool=False)->None:
		self.gate=gate
		self.failure=failure
		self.batch=batch

	def complete(self,request):
		if self.gate is not None:
			assert self.gate.wait(3),"模型等待点未被测试释放"
		if self.failure=="model":
			raise ModelProviderError("MODEL_TIMEOUT","模拟超时")
		observations=[json.loads(message["content"]) for message in request.messages if message["role"]=="tool"]
		if not observations:
			arguments={"service_name":"" if self.failure=="tool" else "order-service"}
			calls=tuple(ToolCall(f"call-{index}","query_thread_pool_snapshot",arguments) for index in range(2 if self.batch else 1))
			response=ToolCallBatch(calls) if self.batch else calls[0]
		elif self.failure=="draft":
			response=StructuredFinalAnswer({"unexpected":True})
		else:
			ids=[item["evidence_id"] for item in observations]
			response=StructuredFinalAnswer({"root_cause":{"text":"线程池满载，原因待核实","evidence_ids":ids},
				"recommendations":[{"text":"补查调用链","evidence_ids":ids}],"confidence":0.5,"limitations":"仅有快照"})
		return ProviderResponse(response,request.model,None)

	def close(self):
		pass


def assembly_for(provider=None,tools=None):
	return build_agent_diagnosis_assembly(provider or TestProvider(),"test",tools or (build_thread_pool_tool(),),
		"order-service",max_steps=3)


def parse_events(text:str)->list[dict]:
	return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_stream_api_emits_ordered_events_and_final_result():
	with TestClient(create_app(assembly_for())) as client:
		response=client.post("/api/v1/agent/diagnosis/stream",json={"description":"排查线程池"})
	assert response.status_code==200
	assert response.headers["content-type"].startswith("text/event-stream")
	assert response.headers["x-accel-buffering"]=="no"
	events=parse_events(response.text)
	assert [item["event"] for item in events]==["run_started","model_started","model_finished","tool_started",
		"tool_finished","model_started","model_finished","run_completed"]
	assert [item["sequence"] for item in events]==list(range(1,9))
	assert len({item["run_id"] for item in events})==1
	result=events[-1]["data"]["result"]
	assert result["status"]=="succeeded" and result["report"] is not None
	assert result["run_id"]==events[0]["run_id"]
	assert "补查调用链" in response.text


@pytest.mark.parametrize("failure,error_code",[("model","MODEL_TIMEOUT"),("tool","INVALID_ARGUMENTS"),("draft","MODEL_PROTOCOL_ERROR")])
def test_stream_failure_is_terminal_event_with_http_200(failure,error_code):
	with TestClient(create_app(assembly_for(TestProvider(failure=failure)))) as client:
		response=client.post("/api/v1/agent/diagnosis/stream",json={"description":"故障实验"})
	events=parse_events(response.text)
	assert response.status_code==200
	assert events[-1]["event"]=="run_failed"
	assert events[-1]["data"]["result"]["error_code"]==error_code
	assert sum(item["event"] in ("run_completed","run_failed") for item in events)==1
	if failure=="tool":
		finished=next(item for item in events if item["event"]=="tool_finished")
		assert finished["data"]["handler_started_at"] is None
		assert finished["data"]["error_code"]=="INVALID_ARGUMENTS"


def test_blank_description_is_rejected_before_stream():
	with TestClient(create_app(assembly_for())) as client:
		response=client.post("/api/v1/agent/diagnosis/stream",json={"description":" "})
	assert response.status_code==422
	assert "text/event-stream" not in response.headers["content-type"]


def test_real_asgi_delivery_precedes_model_completion_and_disconnect_keeps_run():
	# TestClient会缓冲整个响应；直接检查ASGI send，避免把最终回放误当实时流。
	async def scenario():
		gate=Event()
		assembly=assembly_for(TestProvider(gate=gate))
		app=create_app(assembly)
		body=json.dumps({"description":"实时性实验"}).encode()
		disconnect=asyncio.Event()
		model_started=asyncio.Event()
		sent=[]
		first=True
		async def receive():
			nonlocal first
			if first:
				first=False
				return {"type":"http.request","body":body,"more_body":False}
			await disconnect.wait()
			return {"type":"http.disconnect"}
		async def send(message):
			sent.append(message)
			if b"event: model_started" in message.get("body",b""):
				model_started.set()
		scope={"type":"http","asgi":{"version":"3.0","spec_version":"2.3"},"http_version":"1.1",
			"method":"POST","scheme":"http","path":"/api/v1/agent/diagnosis/stream","raw_path":b"/api/v1/agent/diagnosis/stream",
			"query_string":b"","root_path":"","headers":[(b"content-type",b"application/json")],
			"server":("localhost",8000),"client":("localhost",1234)}
		terminal=[]
		original=assembly.diagnosis_service._execute_run
		def execute(run,events):
			result=original(run,events)
			terminal.append(result)
			return result
		assembly.diagnosis_service._execute_run=execute
		async with app.router.lifespan_context(app):
			task=asyncio.create_task(app(scope,receive,send))
			try:
				await asyncio.wait_for(model_started.wait(),1)
				assert not gate.is_set()
				assert not terminal
				disconnect.set()
				await asyncio.wait_for(task,1)
			finally:
				gate.set()
		assert len(terminal)==1 and terminal[0].run.status.value=="succeeded"
		assert b"event: run_completed" not in b"".join(item.get("body",b"") for item in sent)
	asyncio.run(scenario())


def test_parallel_tool_events_share_run_sequence_without_serializing_handlers():
	barrier=Barrier(2)
	spec=build_thread_pool_tool()
	def handler(arguments):
		barrier.wait(timeout=2)
		return spec.handler(arguments)
	assembly=assembly_for(TestProvider(batch=True),(replace(spec,handler=handler),))
	events=[]
	try:
		result=assembly.diagnosis_service.execute("parallel","诊断",event_sink=events.append)
	finally:
		assembly.close()
	assert result.run.status.value=="succeeded"
	tools=[item for item in events if item["event"].startswith("tool_")]
	assert [item["event"] for item in tools[:2]]==["tool_started","tool_started"]
	assert {item["data"]["tool_call_id"] for item in tools}=={"call-0","call-1"}
	assert [item["sequence"] for item in events]==list(range(1,len(events)+1))


def test_concurrent_runs_do_not_mix_events():
	assembly=assembly_for()
	left=[]
	right=[]
	try:
		with ThreadPoolExecutor(max_workers=2) as executor:
			futures=[executor.submit(assembly.diagnosis_service.execute,"left","诊断A",left.append),
				executor.submit(assembly.diagnosis_service.execute,"right","诊断B",right.append)]
			results=[future.result(timeout=3) for future in futures]
	finally:
		assembly.close()
	assert results[0].run.run_id!=results[1].run.run_id
	for events,result in zip((left,right),results):
		assert {item["run_id"] for item in events}=={result.run.run_id}
		assert events[0]["sequence"]==1
		assert events[-1]["data"]["result"]["run_id"]==result.run.run_id


@pytest.mark.parametrize("operation",["create","complete"])
def test_persistence_failure_never_emits_run_completed(operation):
	assembly=assembly_for()
	order=[]
	class Persistence:
		@contextmanager
		def transaction(self):
			yield self
			order.append("commit")
			if operation=="complete":
				raise RuntimeError("secret database details")
		class RunStore:
			def update(self,run):
				pass
		class Store:
			def create(self,item):
				pass
			def create_many(self,*args):
				pass
		run=RunStore()
		evidence=Store()
		report=Store()
		execution_record=Store()
	def create(run):
		if operation=="create":
			raise RunPersistenceError("create",run.run_id)
	assembly.diagnosis_service._persist_create=create
	assembly.diagnosis_service._persist_update=lambda run:None
	assembly.diagnosis_service._diagnosis_persistence=Persistence()
	events=[]
	try:
		with pytest.raises(RunPersistenceError):
			assembly.diagnosis_service.execute("persist","诊断",events.append)
	finally:
		assembly.close()
	assert events[-1]["event"]=="run_failed"
	assert events[-1]["data"]["error_code"]=="PERSISTENCE_FAILED"
	assert not any(item["event"]=="run_completed" for item in events)
	assert "secret database details" not in json.dumps(events)


def test_completed_event_follows_persistence_completion():
	assembly=assembly_for()
	order=[]
	assembly.diagnosis_service._persist_create=lambda run:None
	assembly.diagnosis_service._persist_update=lambda run:None
	assembly.diagnosis_service._diagnosis_persistence=object()
	assembly.diagnosis_service._persist_success=lambda *args:order.append("committed")
	try:
		assembly.diagnosis_service.execute("persist","诊断",lambda event:order.append(event["event"]))
	finally:
		assembly.close()
	assert order[-2:]==["committed","run_completed"]


def test_channel_overflow_is_explicit_and_bounded():
	channel=EventChannel(capacity=2)
	events=RunEvents("run-test",channel.publish)
	for number in range(100):
		events.emit("model_started",number=number)
	failed=channel.pop()
	assert failed["event"]=="stream_failed"
	assert failed["data"]["error_code"]=="EVENT_BUFFER_OVERFLOW"
	assert channel.pop() is None


def test_heartbeat_and_generator_close_stop_accumulation():
	async def scenario():
		channel=EventChannel()
		stream=channel.stream(heartbeat_seconds=0.01,poll_seconds=0.005)
		assert await anext(stream)==": connected\n\n"
		assert await asyncio.wait_for(anext(stream),0.5)==": heartbeat\n\n"
		await stream.aclose()
		RunEvents("closed",channel.publish).emit("model_started")
		assert channel.pop() is None
	asyncio.run(scenario())


def test_capacity_remains_reserved_until_disconnected_work_finishes():
	gate=Event()
	started=Event()
	finished=Event()
	class Service:
		def execute(self,*args,**kwargs):
			started.set()
			assert gate.wait(2)
			finished.set()
	runner=DiagnosisStreamRunner(Service(),max_runs=1)
	try:
		channel=runner.start("first")
		assert started.wait(1)
		channel.close()
		with pytest.raises(StreamBusyError):
			runner.start("second")
	finally:
		gate.set()
		runner.close()
	assert finished.is_set()


def test_event_sink_failure_does_not_fail_diagnosis():
	assembly=assembly_for()
	def broken(event):
		raise RuntimeError("observer failed")
	try:
		result=assembly.diagnosis_service.execute("sink","诊断",broken)
	finally:
		assembly.close()
	assert result.run.status.value=="succeeded"


def test_sse_json_escapes_embedded_newlines():
	events=[]
	RunEvents("run-test",events.append).emit("run_failed",message="line1\nevent: fake\n\n中文")
	encoded=encode_event(events[0])
	assert encoded.count("\ndata: ")==1
	assert encoded.count("\nevent: ")==1
	assert parse_events(encoded)[0]["data"]["message"].endswith("中文")


def test_stream_api_busy_returns_429_before_response_starts(monkeypatch):
	def busy(self,description):
		raise StreamBusyError("并发已满")
	monkeypatch.setattr(DiagnosisStreamRunner,"start",busy)
	with TestClient(create_app(assembly_for())) as client:
		response=client.post("/api/v1/agent/diagnosis/stream",json={"description":"诊断"})
	assert response.status_code==429
	assert response.json()["error_code"]=="STREAM_BUSY"


def test_http_client_receives_progress_before_releasing_model_gate():
	# 用真实localhost TCP连接验证传输层也会逐段发送，不能只依赖缓冲TestClient。
	gate=Event()
	server=uvicorn.Server(uvicorn.Config(create_app(assembly_for(TestProvider(gate=gate))),
		log_level="error",lifespan="on"))
	with socket.socket() as listener:
		listener.bind(("127.0.0.1",0))
		port=listener.getsockname()[1]
		thread=Thread(target=server.run,kwargs={"sockets":[listener]},daemon=True)
		thread.start()
		try:
			deadline=monotonic()+3
			while not server.started and thread.is_alive() and monotonic()<deadline:
				sleep(0.01)
			assert server.started
			with httpx.Client(timeout=3,trust_env=False) as client:
				with client.stream("POST",f"http://127.0.0.1:{port}/api/v1/agent/diagnosis/stream",
					json={"description":"真实传输验证"}) as response:
					assert response.status_code==200
					events=[]
					for line in response.iter_lines():
						if not line.startswith("data: "):
							continue
						event=json.loads(line[6:])
						events.append(event)
						if event["event"]=="model_started":
							if not gate.is_set():
								assert events[-2]["event"]=="run_started"
								gate.set()
					assert events[-1]["event"]=="run_completed"
		finally:
			gate.set()
			server.should_exit=True
			thread.join(timeout=4)
			assert not thread.is_alive()
