from datetime import UTC,datetime
from hashlib import sha256

from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport
from evidenceops.domain.evidence import Evidence,EvidenceSource


def make_evidence(run_id:str,evidence_id:str="ev-001")->Evidence:
	raw_content=f"{evidence_id}:active_threads=64 limit=64"
	content_hash=sha256(raw_content.encode("utf-8")).hexdigest()
	return Evidence(evidence_id,run_id,EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限",f"rpc.log:{evidence_id}",content_hash)


class SuccessfulCollector:
	def collect(self,run):
		return (make_evidence(run.run_id),)


class FailingCollector:
	def collect(self,run):
		raise TimeoutError("mock collector timeout")


class SuccessfulReportGenerator:
	def generate(self,run,evidences):
		evidence_id=evidences[0].evidence_id
		root_cause=DiagnosisClaim("线程池耗尽可能导致 RPC 超时",(evidence_id,))
		recommendation=DiagnosisClaim("检查线程池配置与任务积压",(evidence_id,))
		return DiagnosisReport(run.run_id,root_cause,(recommendation,),0.8,"当前仅使用 Mock 日志证据")


class InvalidReportGenerator:
	def generate(self,run,evidences):
		root_cause=DiagnosisClaim("线程池耗尽可能导致 RPC 超时",("ev-fake",))
		recommendation=DiagnosisClaim("检查线程池配置与任务积压",("ev-fake",))
		return DiagnosisReport(run.run_id,root_cause,(recommendation,),0.8,"Mock 报告引用了不存在的证据")

class FailingReportGenerator:
	def generate(self,run,evidences):
		raise TimeoutError("mock report generation timeout")

class EmptyCollector:
	def collect(self,run):
		return ()

def test_service_completes_successful_diagnosis()->None:
	service=DiagnosisService(SuccessfulCollector(),SuccessfulReportGenerator(),lambda:"run-001")
	result=service.execute("req-001","分析 RPC 超时")
	assert result.run.status.value=="succeeded"
	assert result.run.error_code is None
	assert len(result.evidences)==1
	assert result.evidences[0].run_id=="run-001"
	assert result.report is not None
	assert result.report.run_id=="run-001"


def test_service_fails_when_evidence_collection_fails()->None:
	service=DiagnosisService(FailingCollector(),SuccessfulReportGenerator(),lambda:"run-002")
	result=service.execute("req-002","分析 RPC 超时")
	assert result.run.status.value=="failed"
	assert result.run.error_code=="EVIDENCE_COLLECTION_FAILED"
	assert result.report is None
	assert result.evidences==()


def test_service_fails_when_report_references_unknown_evidence()->None:
	service=DiagnosisService(SuccessfulCollector(),InvalidReportGenerator(),lambda:"run-003")
	result=service.execute("req-003","分析 RPC 超时")
	assert result.run.status.value=="failed"
	assert result.run.error_code=="INVALID_REPORT_EVIDENCE"
	assert result.report is None
	assert len(result.evidences)==1


def test_service_fails_when_report_generation_times_out()->None:
	service=DiagnosisService(SuccessfulCollector(),FailingReportGenerator(),lambda:"run-004")
	result=service.execute("req-004","分析 RPC 超时")
	assert result.run.status.value=="failed"
	assert result.run.error_code=="REPORT_GENERATION_FAILED"
	assert len(result.evidences)==1
	assert result.report is None

def test_service_fails_before_generating_report_when_evidence_is_empty()->None:
	service=DiagnosisService(EmptyCollector(),SuccessfulReportGenerator(),lambda:"run-005")
	result=service.execute("req-005","分析 RPC 超时")
	assert result.run.status.value=="failed"
	assert result.run.error_code=="EVIDENCE_INSUFFICIENT"
	assert result.evidences==()
	assert result.report is None
