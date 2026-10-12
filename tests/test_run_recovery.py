from datetime import UTC,datetime

import pytest
from fastapi.testclient import TestClient

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.application.run_recovery import recover_interrupted_runs
from evidenceops.application.execution_record import ExecutionRecord
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.domain.evidence import Evidence,EvidenceSource
from evidenceops.infrastructure.database.trace_event_repository import SqlAlchemyTraceEventRepository
from test_trace_event_persistence import persistence,make_assembly,read_events,sample_event


def seed_run(persistence,run_id,status=RunStatus.RUNNING):
	run=DiagnosisRun(run_id,f"req-{run_id}","重启恢复验证")
	if status!=RunStatus.PENDING:
		run.transition(RunStatus.RUNNING)
		if status!=RunStatus.RUNNING:
			run.transition(status,error_code="TEST_FAILURE" if status==RunStatus.FAILED else None)
	with persistence.transaction() as transaction:
		transaction.run.create(run)
	return run


@pytest.mark.parametrize("status",[RunStatus.PENDING,RunStatus.RUNNING])
def test_recovery_atomic_terminal_replay_and_idempotence(persistence,status):
	run=seed_run(persistence,"recover",status)
	with persistence.transaction() as transaction:
		transaction.trace_event.create(sample_event(run.run_id))
		transaction.evidence.create(Evidence("ev-recover",run.run_id,EvidenceSource.LOG,datetime.now(UTC),
			"已提交的证据","test:1","a"*64,None))
		transaction.execution_record.create_many(run.run_id,(ExecutionRecord("tool",datetime.now(UTC),
			datetime.now(UTC),1,"succeeded",run_id=run.run_id,tool_name="query_service_logs"),))
	assembly=make_assembly(persistence)
	with TestClient(create_app(assembly)) as client:
		assert client.app.state.recovered_runs==1
		body=client.get("/api/v1/agent/runs/recover").json()
		assert body["status"]=="failed" and body["error_code"]=="RUN_INTERRUPTED"
		assert body["finished_at"] and bool(body["started_at"])==(status==RunStatus.RUNNING)
		assert len(body["evidences"])==1 and body["report"] is None and len(body["execution_records"])==1
		events=read_events(persistence,run.run_id)
		assert [item["sequence"] for item in events]==[1,2]
		terminal=events[-1]
		assert terminal["event"]=="run_failed"
		assert terminal["data"]["result"]["error_code"]==terminal["data"]["result"]["error_detail"]["code"]=="RUN_INTERRUPTED"
		assert len(terminal["data"]["result"]["evidences"])==1
		assert "event: run_failed" in client.get("/api/v1/agent/runs/recover/events/stream?after=1").text
		assert recover_interrupted_runs(persistence)==0
		assert len(read_events(persistence,run.run_id))==2


@pytest.mark.parametrize("status",[RunStatus.SUCCEEDED,RunStatus.FAILED,RunStatus.CANCELLED])
def test_completed_runs_untouched(persistence,status):
	run=seed_run(persistence,"complete",status)
	assert recover_interrupted_runs(persistence)==0
	with persistence.transaction() as transaction:
		stored=transaction.run.get(run.run_id)
		assert stored.status==status and stored.error_code==run.error_code
	assert read_events(persistence,run.run_id)==()


def test_event_insert_failure_rolls_back_run_and_retry_succeeds(persistence,monkeypatch):
	seed_run(persistence,"rollback")
	original=SqlAlchemyTraceEventRepository.create
	def fail(self,event):
		original(self,event)
		raise RuntimeError("模拟事件保存失败")
	with monkeypatch.context() as changes:
		changes.setattr(SqlAlchemyTraceEventRepository,"create",fail)
		with pytest.raises(RuntimeError):
			recover_interrupted_runs(persistence)
	with persistence.transaction() as transaction:
		assert transaction.run.get("rollback").status==RunStatus.RUNNING
	assert read_events(persistence,"rollback")==()
	assert recover_interrupted_runs(persistence)==1


def test_recovery_rechecks_state_under_transaction(persistence):
	run=seed_run(persistence,"finished-race",RunStatus.SUCCEEDED)
	with persistence.transaction() as transaction:
		assert not transaction.run.mark_interrupted(run.run_id,datetime.now(UTC),"RUN_INTERRUPTED")


@pytest.mark.parametrize("operation",["lock","recovery"])
def test_startup_failure_closes_resources(persistence,monkeypatch,operation):
	assembly=make_assembly(persistence)
	closed=[]
	original=persistence.close
	def close():
		closed.append(True)
		original()
	def fail(*args):
		raise RuntimeError("模拟启动失败")
	monkeypatch.setattr(persistence,"close",close)
	if operation=="lock":
		monkeypatch.setattr(persistence,"acquire_instance_lock",fail)
	else:
		monkeypatch.setattr("evidenceops.api.agent_diagnosis.recover_interrupted_runs",fail)
	with pytest.raises(RuntimeError):
		with TestClient(create_app(assembly)):
			pytest.fail("启动失败不能开放请求")
	assert closed==[True]


def test_partial_batch_commit_is_preserved_and_retry_only_handles_remaining(persistence,monkeypatch):
	seed_run(persistence,"first")
	seed_run(persistence,"second")
	original=SqlAlchemyTraceEventRepository.create
	def fail_second(self,event):
		if event["run_id"]=="second":
			raise RuntimeError("第二个Run失败")
		original(self,event)
	with monkeypatch.context() as changes:
		changes.setattr(SqlAlchemyTraceEventRepository,"create",fail_second)
		with pytest.raises(RuntimeError):
			recover_interrupted_runs(persistence)
	assert len(read_events(persistence,"first"))==1 and read_events(persistence,"second")==()
	assert recover_interrupted_runs(persistence)==1
	assert len(read_events(persistence,"first"))==len(read_events(persistence,"second"))==1


def test_provider_close_failure_still_closes_persistence(persistence,monkeypatch):
	assembly=make_assembly(persistence)
	closed=[]
	def fail():
		raise RuntimeError("Provider关闭失败")
	monkeypatch.setattr(assembly.provider,"close",fail,raising=False)
	monkeypatch.setattr(persistence,"close",lambda:closed.append(True))
	with pytest.raises(RuntimeError):
		assembly.close()
	assert closed==[True]
