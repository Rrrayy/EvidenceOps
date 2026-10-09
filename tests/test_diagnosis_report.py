from datetime import UTC,datetime
from hashlib import sha256

import pytest

from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport,validate_report_evidence
from evidenceops.domain.evidence import Evidence,EvidenceSource


def make_evidence(run_id:str)->Evidence:
	content_hash=sha256(b"active_threads=64 limit=64").hexdigest()
	return Evidence("ev-001",run_id,EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限","rpc.log:120",content_hash)


def make_report(evidence_id:str)->DiagnosisReport:
	root_cause=DiagnosisClaim("线程池耗尽可能导致 RPC 超时",(evidence_id,))
	recommendation=DiagnosisClaim("检查线程池配置与任务积压",(evidence_id,))
	return DiagnosisReport("run-001",root_cause,(recommendation,),0.8,"仅依据当前日志，尚未核对历史指标")


def test_report_accepts_evidence_from_same_run()->None:
	report=make_report("ev-001")
	evidence=make_evidence("run-001")
	validate_report_evidence(report,[evidence])


def test_report_rejects_missing_evidence()->None:
	report=make_report("ev-missing")
	with pytest.raises(ValueError):
		validate_report_evidence(report,[make_evidence("run-001")])


def test_report_rejects_evidence_from_other_run()->None:
	report=make_report("ev-001")
	with pytest.raises(ValueError):
		validate_report_evidence(report,[make_evidence("run-002")])
