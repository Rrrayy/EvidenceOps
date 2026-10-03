from evidenceops.application.agent_diagnosis_factory import (
	AgentDiagnosisAssembly,
	build_agent_diagnosis_assembly,
)
from evidenceops.application.model_protocol import FinalAnswer,ToolCall
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.mocks.thread_pool import build_thread_pool_tool


class ClosableMockProvider(MockProvider):
	def __init__(self,responses):
		super().__init__(responses)
		self.closed=False

	def close(self)->None:
		self.closed=True


def test_factory_builds_connected_agent_diagnosis_assembly()->None:
	provider=MockProvider((
		ToolCall(
			"call-factory-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		FinalAnswer("线程池存在任务积压"),
	))
	assembly=build_agent_diagnosis_assembly(
		provider,
		"mock",
		(build_thread_pool_tool(),),
		"order-service",
	)
	run=DiagnosisRun(
		"run-factory-001",
		"req-factory-001",
		"分析订单服务RPC超时",
	)

	try:
		evidences=assembly.evidence_collector.collect(run)
	finally:
		assembly.close()

	assert isinstance(assembly,AgentDiagnosisAssembly)
	assert len(evidences)==1
	assert evidences[0].run_id==run.run_id
	assert evidences[0].source.value=="metric"


def test_assembly_close_closes_provider_when_supported()->None:
	provider=ClosableMockProvider((FinalAnswer("完成"),))
	assembly=build_agent_diagnosis_assembly(
		provider,
		"mock",
		(build_thread_pool_tool(),),
		"order-service",
	)

	assembly.close()

	assert provider.closed is True
