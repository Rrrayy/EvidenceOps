from evidenceops.application.agent_collection_result import AgentCollectionResult
from evidenceops.application.agent_evidence_collector import AgentEvidenceCollector
from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.application.llm_gateway import LLMGateway
from evidenceops.application.model_protocol import StructuredFinalAnswer,ToolCall
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.domain.diagnosis_run import DiagnosisRun
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


def test_agent_collector_returns_evidence_and_draft()->None:
	runtime=ToolRuntime((build_thread_pool_tool(),),timeout_seconds=1.0)
	provider=MockProvider((
		ToolCall(
			"call-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		StructuredFinalAnswer(build_draft_data("run-agent-evidence-001-thread-pool")),
	))
	loop=AgentLoop(LLMGateway(provider,"mock"),runtime)
	tool_collector=ToolEvidenceCollector(runtime,"order-service")
	collector=AgentEvidenceCollector(loop,tool_collector)
	run=DiagnosisRun("run-agent-evidence-001","req-agent-evidence-001","分析订单服务RPC超时")

	try:
		result=collector.collect(run)
	finally:
		runtime.close()

	assert isinstance(result,AgentCollectionResult)
	assert len(result.evidences)==1
	assert result.evidences[0].run_id==run.run_id
	assert result.evidences[0].source.value=="metric"
	assert result.evidences[0].source_ref==("tool:query_thread_pool_snapshot:" "service:order-service")
	assert isinstance(result.draft,DiagnosisDraft)
	assert result.draft.confidence==0.91
