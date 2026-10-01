from evidenceops.application.agent_evidence_collector import AgentEvidenceCollector
from evidenceops.application.agent_loop import AgentLoop,FinalAnswer,ToolCall
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.mocks.mock_agent_model import ScriptedAgentModel
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def test_agent_loop_result_becomes_evidence()->None:
	runtime=ToolRuntime((build_thread_pool_tool(),),timeout_seconds=1.0)

	model=ScriptedAgentModel((
		ToolCall(
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		FinalAnswer("线程池满载并存在任务积压"),
	))

	loop=AgentLoop(model,runtime)

	tool_collector=ToolEvidenceCollector(runtime,"order-service")
	collector=AgentEvidenceCollector(loop,tool_collector)

	run=DiagnosisRun(
		"run-agent-evidence-001",
		"req-agent-evidence-001",
		"分析订单服务RPC超时",
	)

	try:
		evidences=collector.collect(run)
	finally:
		runtime.close()

	assert len(evidences)==1
	assert evidences[0].run_id==run.run_id
	assert evidences[0].source.value=="metric"
	assert evidences[0].source_ref==(
		"tool:query_thread_pool_snapshot:"
		"service:order-service"
	)