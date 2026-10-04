from evidenceops.application.agent_diagnosis_factory import (
	AgentDiagnosisAssembly,
	build_agent_diagnosis_assembly,
)
from evidenceops.application.model_protocol import FinalAnswer,StructuredFinalAnswer,ToolCall
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.mocks.thread_pool import build_thread_pool_tool


class ClosableMockProvider(MockProvider):
	def __init__(self,responses):
		super().__init__(responses)
		self.closed=False

	def close(self)->None:
		self.closed=True


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


def test_factory_builds_connected_agent_diagnosis_assembly()->None:
	provider=MockProvider((
		ToolCall(
			"call-factory-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		StructuredFinalAnswer(build_draft_data("run-factory-001-thread-pool")),
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
		collection=assembly.evidence_collector.collect(run)
	finally:
		assembly.close()

	assert isinstance(assembly,AgentDiagnosisAssembly)
	assert len(collection.evidences)==1
	assert collection.evidences[0].run_id==run.run_id
	assert collection.evidences[0].source.value=="metric"


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
