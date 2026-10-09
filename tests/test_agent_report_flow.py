from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.diagnosis_report_builder import DraftReportGenerator
from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.application.model_protocol import StructuredFinalAnswer,ToolCall
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def build_draft_data(evidence_id:str)->dict:
	return {
		"root_cause":{
			"text":"线程池耗尽导致RPC请求排队",
			"evidence_ids":[evidence_id],
		},
		"recommendations":[
			{
				"text":"检查线程池容量和任务积压",
				"evidence_ids":[evidence_id],
			},
		],
		"confidence":0.91,
		"limitations":"当前只检查了线程池指标",
	}


def test_agent_main_chain_builds_report()->None:
	provider=MockProvider((
		ToolCall(
			"call-report-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		StructuredFinalAnswer(build_draft_data("run-agent-report-001-call-report-001")),
	))
	assembly=build_agent_diagnosis_assembly(provider,"mock",(build_thread_pool_tool(),),"order-service")
	service=DiagnosisService(assembly.evidence_collector,DraftReportGenerator(),lambda:"run-agent-report-001")

	try:
		result=service.execute("req-agent-report-001","分析订单服务RPC超时")
	finally:
		assembly.close()

	assert result.run.status.value=="succeeded"
	assert result.run.error_code is None
	assert len(result.evidences)==1
	assert result.report is not None
	assert result.report.run_id=="run-agent-report-001"
	assert result.report.root_cause.evidence_ids==("run-agent-report-001-call-report-001",)
	assert result.report.confidence==0.91


def test_agent_main_chain_rejects_unknown_evidence_id()->None:
	provider=MockProvider((
		ToolCall(
			"call-report-002",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		StructuredFinalAnswer(build_draft_data("evidence-does-not-exist")),
	))
	assembly=build_agent_diagnosis_assembly(provider,"mock",(build_thread_pool_tool(),),"order-service")
	service=DiagnosisService(assembly.evidence_collector,DraftReportGenerator(),lambda:"run-agent-report-002")

	try:
		result=service.execute("req-agent-report-002","分析订单服务RPC超时")
	finally:
		assembly.close()

	assert result.run.status.value=="failed"
	assert result.run.error_code=="INVALID_REPORT_EVIDENCE"
	assert result.report is None
	assert len(result.evidences)==1
