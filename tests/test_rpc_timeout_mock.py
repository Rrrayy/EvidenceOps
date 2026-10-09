from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.domain.diagnosis_run import RunStatus
from evidenceops.domain.evidence import EvidenceSource
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator


def test_rpc_timeout_mock_completes_with_three_evidence_sources()->None:
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator(),lambda:"run-rpc-001")
	result=service.execute("req-rpc-001","排查 C++ RPC 超时")
	assert result.run.status is RunStatus.SUCCEEDED
	assert {evidence.source for evidence in result.evidences}=={EvidenceSource.LOG,EvidenceSource.METRIC,EvidenceSource.CONFIG}
	assert result.report is not None
	assert len(result.report.root_cause.evidence_ids)==3
	assert len(result.report.recommendations)==2
