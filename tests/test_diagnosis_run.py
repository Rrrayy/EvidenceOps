import pytest

from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus


def test_valid_lifecycle()->None:
	run=DiagnosisRun("run-001","req-001","分析 RPC 超时")
	assert run.status is RunStatus.PENDING
	run.transition(RunStatus.RUNNING)
	assert run.status is RunStatus.RUNNING
	run.transition(RunStatus.SUCCEEDED)
	assert run.status is RunStatus.SUCCEEDED


def test_invalid_transition_preserves_status()->None:
	run=DiagnosisRun("run-002","req-002","分析 RPC 超时")
	with pytest.raises(ValueError):
		run.transition(RunStatus.SUCCEEDED)
	assert run.status is RunStatus.PENDING


def test_wrong_type_preserves_status()->None:
	run=DiagnosisRun("run-003","req-003","分析 RPC 超时")
	with pytest.raises(TypeError):
		run.transition("running")
	assert run.status is RunStatus.PENDING


def test_timestamps_follow_lifecycle()->None:
	run=DiagnosisRun("run-004","req-004","分析 RPC 超时")
	assert run.created_at.tzinfo is not None
	assert run.started_at is None
	assert run.finished_at is None
	run.transition(RunStatus.RUNNING)
	assert run.started_at is not None
	assert run.finished_at is None
	run.transition(RunStatus.SUCCEEDED)
	assert run.finished_at is not None


def test_cancel_before_start()->None:
	run=DiagnosisRun("run-005","req-005","分析 RPC 超时")
	run.transition(RunStatus.CANCELLED)
	assert run.started_at is None
	assert run.finished_at is not None


def test_failure_requires_error_code()->None:
	run=DiagnosisRun("run-006","req-006","分析 RPC 超时")
	run.transition(RunStatus.RUNNING)
	with pytest.raises(ValueError):
		run.transition(RunStatus.FAILED)
	assert run.status is RunStatus.RUNNING
	assert run.finished_at is None
	run.transition(RunStatus.FAILED,error_code="TOOL_TIMEOUT")
	assert run.status is RunStatus.FAILED
	assert run.error_code=="TOOL_TIMEOUT"
	assert run.finished_at is not None
