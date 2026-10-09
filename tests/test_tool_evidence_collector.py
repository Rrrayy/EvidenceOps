import pytest
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.application.tool_runtime import ToolResult
from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport
from evidenceops.mocks.thread_pool import build_thread_pool_tool

class FailingToolRuntime:
	def execute(self,tool_name:str,arguments:dict)->ToolResult:
		return ToolResult(tool_name=tool_name,ok=False,error_code="TOOL_TIMEOUT",error_message="工具执行超过时间限制")

class ThreadPoolReportGenerator:
	def generate(self,run,evidences):
		evidence=evidences[0]

		root_cause=DiagnosisClaim("线程池满载并存在任务积压，可能导致RPC超时",(evidence.evidence_id,))

		recommendation=DiagnosisClaim("检查线程池容量、任务耗时和下游RPC状态",(evidence.evidence_id,))

		return DiagnosisReport(
			run_id=run.run_id,
			root_cause=root_cause,
			recommendations=(recommendation,),
			confidence=0.8,
			limitations="当前证据来自Mock线程池工具",
		)


def test_tool_collector_integrates_with_diagnosis_service():
	runtime=ToolRuntime((build_thread_pool_tool(),),timeout_seconds=1.0)

	collector=ToolEvidenceCollector(runtime,"order-service")

	service=DiagnosisService(
		evidence_collector=collector,
		report_generator=ThreadPoolReportGenerator(),
		run_id_factory=lambda:"run-tool-001",
	)

	try:
		result=service.execute(request_id="req-tool-001",description="分析订单服务RPC超时")
	finally:
		runtime.close()

	assert result.run.status.value=="succeeded"

	assert result.run.error_code is None

	assert len(result.evidences)==1

	evidence=result.evidences[0]

	assert evidence.run_id=="run-tool-001"

	assert evidence.source.value=="metric"

	assert evidence.source_ref==("tool:query_thread_pool_snapshot:" "service:order-service")

	assert result.report is not None

	assert result.report.run_id=="run-tool-001"

	assert result.report.root_cause.evidence_ids==(evidence.evidence_id,)

	assert result.report.recommendations[0].evidence_ids==(evidence.evidence_id,)

def test_tool_collector_preserves_tool_error_code()->None:
	collector=ToolEvidenceCollector(FailingToolRuntime(),"order-service")

	run=DiagnosisRun(run_id="run-tool-error-001",request_id="req-tool-error-001",description="测试工具超时")

	with pytest.raises(ToolCollectionError) as error_info:
		collector.collect(run)

	assert error_info.value.error_code=="TOOL_TIMEOUT"
	assert error_info.value.error_message=="工具执行超过时间限制"


def test_service_converts_tool_failure_to_collection_failure()->None:
	runtime=FailingToolRuntime()

	collector=ToolEvidenceCollector(runtime,"order-service")

	service=DiagnosisService(
		evidence_collector=collector,
		report_generator=ThreadPoolReportGenerator(),
		run_id_factory=lambda:"run-tool-error-002",
	)

	result=service.execute(request_id="req-tool-error-002",description="测试工具超时")

	assert result.run.status.value=="failed"

	assert result.run.error_code=="EVIDENCE_COLLECTION_FAILED"

	assert result.evidences==()

	assert result.report is None
