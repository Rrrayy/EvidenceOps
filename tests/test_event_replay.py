import asyncio
import json
import socket
from threading import Event,Thread
from time import monotonic,sleep

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.api.event_replay import EventReplay,ReplayBusyError
from evidenceops.application.event_history import EventHistoryError,load_event_page,parse_event_cursor
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.infrastructure.database.trace_event_repository import SqlAlchemyTraceEventRepository
from test_trace_event_persistence import persistence,make_assembly,read_events,sample_event
from test_diagnosis_stream import parse_events,TestProvider
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def test_json_pagination_and_terminal_replay_do_not_execute_model(persistence):
	assembly=make_assembly(persistence)
	result=assembly.diagnosis_service.execute("req-history","历史补发")
	stored=read_events(persistence,result.run.run_id)
	def forbidden(*args,**kwargs):
		raise AssertionError("重放不能执行诊断")
	assembly.diagnosis_service.execute=forbidden
	with TestClient(create_app(assembly)) as client:
		path=f"/api/v1/agent/runs/{result.run.run_id}/events"
		cursor=0
		combined=[]
		while True:
			response=client.get(path,params={"after":cursor,"limit":2})
			assert response.status_code==200
			page=response.json()
			combined.extend(page["events"])
			cursor=page["next_sequence"]
			if not page["has_more"]:
				break
		assert combined==list(stored)
		stream=client.get(path+"/stream",headers={"Last-Event-ID":f"{result.run.run_id}:5"})
		assert stream.status_code==200
		assert parse_events(stream.text)==list(stored[5:])
		assert client.get(path+"/stream?after=8").text==": connected\n\n"
		assert parse_events(client.get(path+"/stream").text)==list(stored)


@pytest.mark.parametrize("tail,headers,status,code",[
	("?after=-1",{},422,None),("?limit=0",{},422,None),("?limit=1001",{},422,None),
	("?after=999",{},409,"INVALID_EVENT_CURSOR"),
	("/stream",{"Last-Event-ID":"other:1"},422,"INVALID_ARGUMENTS"),
	("/stream",{"Last-Event-ID":"broken"},422,"INVALID_ARGUMENTS"),
	("/stream",{"Last-Event-ID":"{run_id}:-1"},422,"INVALID_ARGUMENTS"),
	("/stream?after=2",{"Last-Event-ID":"{run_id}:3"},422,"INVALID_ARGUMENTS"),
	("/stream",{"Last-Event-ID":"{run_id}:999"},409,"INVALID_EVENT_CURSOR")])
def test_invalid_cursor_rejected_before_sse(persistence,tail,headers,status,code):
	assembly=make_assembly(persistence)
	result=assembly.diagnosis_service.execute("req-validation","游标校验")
	with TestClient(create_app(assembly)) as client:
		headers={name:value.format(run_id=result.run.run_id) for name,value in headers.items()}
		response=client.get(f"/api/v1/agent/runs/{result.run.run_id}/events{tail}",headers=headers)
		assert response.status_code==status
		assert "text/event-stream" not in response.headers["content-type"]
		if code:
			assert response.json()["error_code"]==code


@pytest.mark.parametrize("suffix",["","/stream"])
def test_missing_and_disabled_persistence(persistence,suffix):
	assembly=make_assembly(persistence)
	with TestClient(create_app(assembly)) as client:
		assert client.get(f"/api/v1/agent/runs/missing/events{suffix}").status_code==404
	assembly=make_assembly(None)
	with TestClient(create_app(assembly)) as client:
		response=client.get(f"/api/v1/agent/runs/missing/events{suffix}")
		assert response.status_code==503 and response.json()["error_code"]=="PERSISTENCE_DISABLED"


def test_legacy_terminal_run_has_no_fabricated_events(persistence):
	run=DiagnosisRun("run-legacy","req-legacy","旧Run")
	run.transition(RunStatus.RUNNING)
	run.transition(RunStatus.FAILED,error_code="OLD_ERROR")
	with persistence.transaction() as transaction:
		transaction.run.create(run)
	assembly=make_assembly(persistence)
	with TestClient(create_app(assembly)) as client:
		path="/api/v1/agent/runs/run-legacy/events"
		assert client.get(path).json()["events"]==[]
		assert parse_events(client.get(path+"/stream").text)==[]


def test_history_gap_and_storage_error_are_explicit(persistence,monkeypatch):
	run=DiagnosisRun("run-gap","req-gap","事件缺口")
	with persistence.transaction() as transaction:
		transaction.run.create(run)
		transaction.trace_event.create(sample_event(run.run_id,2))
	assembly=make_assembly(persistence)
	with TestClient(create_app(assembly)) as client:
		path="/api/v1/agent/runs/run-gap/events"
		assert client.get(path).json()["error_code"]=="EVENT_HISTORY_GAP"
		assert client.get(path+"/stream").status_code==409
		def broken(*args,**kwargs):
			raise RuntimeError("secret database url")
		monkeypatch.setattr(SqlAlchemyTraceEventRepository,"get_max_sequence",broken)
		for tail in ("","/stream"):
			response=client.get(path+tail)
			assert response.status_code==503 and "secret" not in response.text


def test_live_replay_follows_database_without_holding_sessions(persistence):
	async def scenario():
		run=DiagnosisRun("run-live","req-live","活跃订阅")
		run.transition(RunStatus.RUNNING)
		with persistence.transaction() as transaction:
			transaction.run.create(run)
			transaction.trace_event.create(sample_event(run.run_id,1))
		page=load_event_page(persistence,run.run_id)
		replay=EventReplay(persistence,max_connections=1,poll_seconds=0.005,heartbeat_seconds=0.01,page_size=1)
		lease=replay.reserve()
		stream=lease.stream(page)
		assert await anext(stream)==": connected\n\n"
		assert persistence._engine.pool.checkedout()==0
		assert parse_events(await anext(stream))[0]["sequence"]==1
		assert persistence._engine.pool.checkedout()==0
		# 读完第一页之后提交多条事件；数据库统一供给，不存在订阅切换窗口。
		with persistence.transaction() as transaction:
			transaction.trace_event.create(sample_event(run.run_id,2))
			transaction.trace_event.create(sample_event(run.run_id,3))
		assert parse_events(await asyncio.wait_for(anext(stream),1))[0]["sequence"]==2
		assert parse_events(await asyncio.wait_for(anext(stream),1))[0]["sequence"]==3
		assert await asyncio.wait_for(anext(stream),1)==": heartbeat\n\n"
		run.transition(RunStatus.CANCELLED)
		with persistence.transaction() as transaction:
			transaction.run.update(run)
			item=sample_event(run.run_id,4)
			item["event"]="run_cancelled"
			transaction.trace_event.create(item)
		assert parse_events(await anext(stream))[0]["event"]=="run_cancelled"
		with pytest.raises(StopAsyncIteration):
			await anext(stream)
		replay.reserve().close()
	asyncio.run(scenario())


def test_terminal_commit_between_state_and_event_reads_is_not_missed(persistence,monkeypatch):
	async def scenario():
		run=DiagnosisRun("run-race","req-race","读取终态竞争")
		run.transition(RunStatus.RUNNING)
		with persistence.transaction() as transaction:
			transaction.run.create(run)
			transaction.trace_event.create(sample_event(run.run_id))
		original=SqlAlchemyTraceEventRepository.get_max_sequence
		committed=False
		def commit_between_reads(repository,run_id):
			nonlocal committed
			if not committed:
				committed=True
				run.transition(RunStatus.FAILED,error_code="TEST_FAILURE")
				with persistence.transaction() as transaction:
					transaction.run.update(run)
					item=sample_event(run_id,2)
					item["event"]="run_failed"
					transaction.trace_event.create(item)
			return original(repository,run_id)
		monkeypatch.setattr(SqlAlchemyTraceEventRepository,"get_max_sequence",commit_between_reads)
		page=load_event_page(persistence,run.run_id)
		replay=EventReplay(persistence)
		parts=[part async for part in replay.reserve().stream(page)]
		assert parse_events("".join(parts))[-1]["event"]=="run_failed"
	asyncio.run(scenario())


def test_disconnect_and_read_failure_release_observation_slot(persistence,monkeypatch):
	async def scenario():
		run=DiagnosisRun("run-disconnect","req-disconnect","断连")
		run.transition(RunStatus.RUNNING)
		with persistence.transaction() as transaction:
			transaction.run.create(run)
		page=load_event_page(persistence,run.run_id)
		replay=EventReplay(persistence,max_connections=1,poll_seconds=0.001)
		lease=replay.reserve()
		with pytest.raises(ReplayBusyError):
			replay.reserve()
		stream=lease.stream(page)
		await anext(stream)
		await stream.aclose()
		lease.close()
		second=replay.reserve()
		stream=second.stream(page)
		await anext(stream)
		def broken(*args,**kwargs):
			raise RuntimeError("secret")
		monkeypatch.setattr(SqlAlchemyTraceEventRepository,"get_max_sequence",broken)
		encoded=await anext(stream)
		assert "event: stream_failed" in encoded and "id:" not in encoded and "secret" not in encoded
		with pytest.raises(StopAsyncIteration):
			await anext(stream)
		replay.reserve().close()
	asyncio.run(scenario())


def test_replay_limit_returns_429_without_starting_diagnosis(persistence,monkeypatch):
	def busy(self):
		raise ReplayBusyError("busy")
	monkeypatch.setattr(EventReplay,"reserve",busy)
	assembly=make_assembly(persistence)
	with TestClient(create_app(assembly)) as client:
		assert client.get("/api/v1/agent/runs/any/events/stream").status_code==429


def test_real_tcp_disconnect_and_reconnect_preserve_running_diagnosis(persistence):
	gate=Event()
	assembly=build_agent_diagnosis_assembly(TestProvider(gate=gate),"test",(build_thread_pool_tool(),),
		"order-service",diagnosis_persistence=persistence)
	server=uvicorn.Server(uvicorn.Config(create_app(assembly),log_level="error",lifespan="on"))
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
			with httpx.Client(timeout=4,trust_env=False) as client:
				base=f"http://127.0.0.1:{port}"
				with client.stream("POST",base+"/api/v1/agent/diagnosis/stream",json={"description":"真实断线重连"}) as response:
					for line in response.iter_lines():
						if line.startswith("data: "):
							item=json.loads(line[6:])
							if item["event"]=="model_started":
								break
				path=f"/api/v1/agent/runs/{item['run_id']}"
				assert client.get(base+path).json()["status"]=="running"
				with client.stream("GET",base+path+"/events/stream",headers={"Last-Event-ID":f"{item['run_id']}:1"}) as response:
					assert response.status_code==200
					collected=[]
					for line in response.iter_lines():
						if line.startswith("data: "):
							replayed=json.loads(line[6:])
							collected.append(replayed)
							if replayed["event"]=="model_started":
								# 确认重连接收发生在模型完成前，再放行模型。
								if len(collected)==1:
									assert not gate.is_set()
								gate.set()
					assert [entry["sequence"] for entry in collected]==list(range(2,9))
					assert collected[-1]["event"]=="run_completed"
				assert client.get(base+path).json()["status"]=="succeeded"
				assert len(client.get(base+path+"/events").json()["events"])==8
		finally:
			gate.set()
			server.should_exit=True
			thread.join(5)
			assert not thread.is_alive()


@pytest.mark.parametrize("failure",["model","draft"])
def test_failed_run_replay_ends_at_saved_failure(persistence,failure):
	assembly=make_assembly(persistence,failure)
	result=assembly.diagnosis_service.execute("req-failed-replay","失败回放")
	with TestClient(create_app(assembly)) as client:
		response=client.get(f"/api/v1/agent/runs/{result.run.run_id}/events/stream")
		items=parse_events(response.text)
		assert items[-1]["event"]=="run_failed"
		assert items[-1]["data"]["result"]["error_code"]==result.run.error_code


@pytest.mark.parametrize("value",["run-cursor:９","run-cursor:+1","run-cursor:"+"9"*5000,
	"run-cursor:9223372036854775808"])
def test_cursor_rejects_non_ascii_and_oversized_sequence(value):
	with pytest.raises(EventHistoryError) as captured:
		parse_event_cursor("run-cursor",None,value)
	assert captured.value.status_code==422


def test_matching_header_and_query_are_accepted(persistence):
	assembly=make_assembly(persistence)
	result=assembly.diagnosis_service.execute("req-both","双游标")
	with TestClient(create_app(assembly)) as client:
		response=client.get(f"/api/v1/agent/runs/{result.run.run_id}/events/stream?after=7",
			headers={"Last-Event-ID":f"{result.run.run_id}:7"})
		assert [item["sequence"] for item in parse_events(response.text)]==[8]


def test_terminal_replay_reads_multiple_database_pages(persistence):
	async def scenario():
		assembly=make_assembly(persistence)
		try:
			result=assembly.diagnosis_service.execute("req-many-pages","跨页终态")
			replay=EventReplay(persistence,page_size=2)
			first=load_event_page(persistence,result.run.run_id,0,2)
			encoded="".join([part async for part in replay.reserve().stream(first)])
			assert [item["sequence"] for item in parse_events(encoded)]==list(range(1,9))
		finally:
			assembly.close()
	asyncio.run(scenario())
