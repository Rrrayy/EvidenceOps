from datetime import UTC,datetime
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event,select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.api.diagnosis_stream import EventChannel,encode_event
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.run_events import EventPersistenceError,RunEvents
from evidenceops.application.run_repository import RunPersistenceError
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.models import Base,TraceEventRow
from evidenceops.infrastructure.database.trace_event_repository import SqlAlchemyTraceEventRepository
from evidenceops.mocks.thread_pool import build_thread_pool_tool
from test_diagnosis_stream import TestProvider


@pytest.fixture
def persistence(tmp_path):
	# 文件数据库允许独立连接验证提交可见性，避免共享内存连接掩盖事务边界。
	engine=create_engine(f"sqlite:///{tmp_path/'events.db'}",connect_args={"check_same_thread":False})
	@event.listens_for(engine,"connect")
	def enable_foreign_keys(connection,record):
		connection.execute("PRAGMA foreign_keys=ON")
	Base.metadata.create_all(engine)
	store=SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)
	try:
		yield store
	finally:
		store.close()


def make_assembly(persistence,failure=None,batch=False):
	return build_agent_diagnosis_assembly(TestProvider(failure=failure,batch=batch),"test",
		(build_thread_pool_tool(),),"order-service",diagnosis_persistence=persistence)


def read_events(persistence,run_id):
	with persistence.transaction() as transaction:
		return transaction.trace_event.list_by_run(run_id)


def sample_event(run_id,sequence=1):
	return {"run_id":run_id,"sequence":sequence,"event":"tool_finished",
		"occurred_at":datetime.now(UTC).isoformat(),"data":{"text":"中文\n第二行","nested":{"value":1}}}


@pytest.mark.parametrize("failure,terminal",[(None,"run_completed"),("model","run_failed"),("tool","run_failed"),("draft","run_failed")])
def test_stream_delivers_only_committed_events_and_atomic_terminal(persistence,failure,terminal):
	assembly=make_assembly(persistence,failure)
	delivered=[]
	def sink(item):
		saved=read_events(persistence,item["run_id"])
		assert saved[-1]["sequence"]==item["sequence"]
		assert saved[-1]["data"]==item["data"]
		if item["event"]==terminal:
			with persistence.transaction() as transaction:
				assert transaction.run.get(item["run_id"]).status.value==item["data"]["result"]["status"]
		delivered.append(item)
	try:
		result=assembly.diagnosis_service.execute("req-visible","提交可见性",sink)
		stored=read_events(persistence,result.run.run_id)
		assert stored[-1]["event"]==terminal
		assert [item["sequence"] for item in stored]==list(range(1,len(stored)+1))
		assert [(item["event"],item["data"]) for item in stored]==[(item["event"],item["data"]) for item in delivered]
	finally:
		assembly.close()


def test_plain_http_without_sink_still_persists_full_event_history(persistence):
	assembly=make_assembly(persistence)
	with TestClient(create_app(assembly)) as client:
		response=client.post("/api/v1/agent/diagnosis",json={"description":"普通HTTP也归档事件"})
		assert response.status_code==200
		stored=read_events(persistence,response.json()["run_id"])
		assert len(stored)==8 and stored[-1]["event"]=="run_completed"


def test_closed_sse_channel_does_not_stop_persistence(persistence):
	assembly=make_assembly(persistence)
	channel=EventChannel()
	channel.close()
	try:
		result=assembly.diagnosis_service.execute("req-disconnected","断线保存",channel.publish)
		assert channel.pop() is None
		assert len(read_events(persistence,result.run.run_id))==8
	finally:
		assembly.close()


def test_parallel_tools_are_persisted_with_unique_contiguous_sequence(persistence):
	assembly=make_assembly(persistence,batch=True)
	try:
		result=assembly.diagnosis_service.execute("req-parallel","并发归档")
		stored=read_events(persistence,result.run.run_id)
		assert result.run.status is RunStatus.SUCCEEDED
		assert len(stored)==10
		assert [item["sequence"] for item in stored]==list(range(1,11))
		assert sum(item["event"]=="tool_finished" for item in stored)==2
	finally:
		assembly.close()


def test_cancellation_is_atomic_and_cancel_request_saved_once(persistence):
	assembly=make_assembly(persistence)
	decisions=[]
	def cancel(item):
		if item["event"]=="model_started":
			decisions.append(assembly.diagnosis_service.request_cancel(item["run_id"]))
			decisions.append(assembly.diagnosis_service.request_cancel(item["run_id"]))
	try:
		result=assembly.diagnosis_service.execute("req-cancel","取消归档",cancel)
		stored=read_events(persistence,result.run.run_id)
		assert result.run.status is RunStatus.CANCELLED
		assert decisions[1]["already_requested"]
		assert sum(item["event"]=="run_cancel_requested" for item in stored)==1
		assert stored[-1]["event"]=="run_cancelled"
		assert stored[-1]["data"]["result"]["report"] is None
	finally:
		assembly.close()


@pytest.mark.parametrize("failure,terminal",[(None,"run_completed"),("model","run_failed")])
def test_terminal_event_insert_failure_rolls_back_business_data(persistence,monkeypatch,failure,terminal):
	assembly=make_assembly(persistence,failure)
	create=SqlAlchemyTraceEventRepository.create
	def broken_terminal(self,item):
		if item["event"]==terminal:
			raise RuntimeError("private database detail")
		create(self,item)
	monkeypatch.setattr(SqlAlchemyTraceEventRepository,"create",broken_terminal)
	delivered=[]
	try:
		with pytest.raises(RunPersistenceError) as captured:
			assembly.diagnosis_service.execute("req-rollback","终态回滚",delivered.append)
		run_id=captured.value.run_id
		with persistence.transaction() as transaction:
			assert transaction.run.get(run_id).status is RunStatus.RUNNING
			assert transaction.report.get(run_id) is None
			assert transaction.evidence.list_by_run(run_id)==()
			assert transaction.execution_record.list_by_run(run_id)==()
		assert read_events(persistence,run_id)[-1]["event"]=="model_finished"
		assert delivered[-1]["event"]=="stream_failed"
		assert not encode_event(delivered[-1]).startswith("id:")
	finally:
		assembly.close()


def test_real_commit_failure_rolls_back_terminal_and_report(persistence):
	assembly=make_assembly(persistence)
	@event.listens_for(persistence._session_factory,"before_commit")
	def reject_terminal(session):
		if session.scalar(select(TraceEventRow.event_type).order_by(TraceEventRow.sequence.desc()).limit(1))=="run_completed":
			raise RuntimeError("simulated commit failure")
	try:
		with pytest.raises(RunPersistenceError) as captured:
			assembly.diagnosis_service.execute("req-commit","提交阶段回滚")
		event.remove(persistence._session_factory,"before_commit",reject_terminal)
		with persistence.transaction() as transaction:
			assert transaction.run.get(captured.value.run_id).status is RunStatus.RUNNING
			assert transaction.report.get(captured.value.run_id) is None
		assert read_events(persistence,captured.value.run_id)[-1]["event"]=="model_finished"
	finally:
		if event.contains(persistence._session_factory,"before_commit",reject_terminal):
			event.remove(persistence._session_factory,"before_commit",reject_terminal)
		assembly.close()


def test_process_event_failure_stops_before_model_and_returns_safe_http_error(persistence,monkeypatch):
	assembly=make_assembly(persistence)
	create=SqlAlchemyTraceEventRepository.create
	def broken_start(self,item):
		if item["event"]=="model_started":
			raise RuntimeError("secret database detail")
		create(self,item)
	monkeypatch.setattr(SqlAlchemyTraceEventRepository,"create",broken_start)
	with TestClient(create_app(assembly)) as client:
		response=client.post("/api/v1/agent/diagnosis",json={"description":"事件保存故障"})
		assert response.status_code==503 and response.json()["error_code"]=="PERSISTENCE_FAILED"
		assert "secret" not in response.text
		stored=read_events(persistence,response.json()["run_id"])
		assert [item["event"] for item in stored]==["run_started"]


def test_commit_failure_does_not_publish_or_advance_cursor():
	delivered=[]
	def fail(item):
		raise RuntimeError("commit failed")
	events=RunEvents("run-commit",delivered.append,fail)
	with pytest.raises(EventPersistenceError):
		events.emit("run_started")
	assert not delivered and events._sequence==0
	with pytest.raises(EventPersistenceError):
		events.emit("model_started")


def test_repository_constraints_pagination_and_payload_snapshot(persistence):
	run=DiagnosisRun("run-store","req-store","仓储约束")
	item=sample_event(run.run_id)
	with persistence.transaction() as transaction:
		transaction.run.create(run)
		transaction.trace_event.create(item)
		item["data"]["nested"]["value"]=9
		transaction.trace_event.create(sample_event(run.run_id,2))
	with persistence.transaction() as transaction:
		assert transaction.trace_event.get_max_sequence(run.run_id)==2
		assert transaction.trace_event.get_max_sequence("missing")==0
		assert transaction.trace_event.list_by_run(run.run_id,0,1)[0]["data"]["nested"]["value"]==1
		assert transaction.trace_event.list_by_run(run.run_id,1,1)[0]["sequence"]==2
	with pytest.raises(IntegrityError),persistence.transaction() as transaction:
		transaction.trace_event.create(sample_event(run.run_id))
	with pytest.raises(IntegrityError),persistence.transaction() as transaction:
		transaction.trace_event.create(sample_event("missing"))
	with persistence.transaction() as transaction:
		assert len(transaction.trace_event.list_by_run(run.run_id))==2


@pytest.mark.parametrize("after,limit",[(-1,100),(True,100),(0,0),(0,1002)])
def test_repository_rejects_invalid_page_parameters(persistence,after,limit):
	with persistence.transaction() as transaction,pytest.raises(ValueError):
		transaction.trace_event.list_by_run("run-check",after,limit)


def test_terminal_seals_late_events_and_observer_cannot_modify_saved_payload():
	saved=[]
	def mutate(item):
		item["data"]["value"]=99
	events=RunEvents("run-sealed",mutate,saved.append)
	events.emit("run_started",value=1)
	events.finish("run_completed",{"value":2},saved.append)
	events.emit("tool_finished",value=3)
	assert [item["data"]["value"] for item in saved]==[1,2]


def test_storage_survives_new_repository_instance(persistence):
	assembly=make_assembly(persistence)
	try:
		result=assembly.diagnosis_service.execute("req-reopen","新仓储读取")
		other=SqlAlchemyDiagnosisPersistence(persistence._session_factory)
		assert read_events(other,result.run.run_id)[-1]["event"]=="run_completed"
	finally:
		assembly.close()


def test_concurrent_runs_keep_independent_event_sequences(persistence):
	assembly=make_assembly(persistence)
	try:
		with ThreadPoolExecutor(max_workers=2) as executor:
			futures=[executor.submit(assembly.diagnosis_service.execute,f"req-{number}","并发Run") for number in range(2)]
			results=[future.result(5) for future in futures]
		assert results[0].run.run_id!=results[1].run.run_id
		for result in results:
			stored=read_events(persistence,result.run.run_id)
			assert [item["sequence"] for item in stored]==list(range(1,9))
			assert {item["run_id"] for item in stored}=={result.run.run_id}
	finally:
		assembly.close()


def test_cancel_from_started_callback_preserves_first_event_and_skips_model(persistence):
	assembly=make_assembly(persistence)
	def cancel_started(item):
		if item["event"]=="run_started":
			assembly.diagnosis_service.request_cancel(item["run_id"])
	try:
		result=assembly.diagnosis_service.execute("req-start-cancel","开始时取消",cancel_started)
		stored=read_events(persistence,result.run.run_id)
		assert [item["event"] for item in stored]==["run_started","run_cancel_requested","run_cancelled"]
		assert result.execution_records==()
	finally:
		assembly.close()
