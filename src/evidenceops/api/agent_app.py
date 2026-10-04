import os

from evidenceops.application.agent_diagnosis_factory import (
	build_agent_diagnosis_assembly,
)
from evidenceops.application.model_protocol import (
	ModelRequest,
	StructuredFinalAnswer,
	ToolCall,
)
from evidenceops.api.agent_diagnosis import create_app
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.infrastructure.providers.openai_compatible_provider import (
	OpenAICompatibleProvider,
)
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def build_final_answer(request:ModelRequest)->StructuredFinalAnswer:
	evidence_id=f"{request.run_id}-call-http-agent-001"

	return StructuredFinalAnswer({
		"root_cause":{
			"text":"线程池耗尽导致RPC请求排队超时",
			"evidence_ids":[evidence_id],
		},
		"recommendations":[
			{
				"text":"检查线程池容量和任务积压情况",
				"evidence_ids":[evidence_id],
			},
		],
		"confidence":0.91,
		"limitations":"当前只检查了线程池指标，尚未核查真实调用链",
	})


def build_agent_app():
	provider=MockProvider((
		ToolCall(
			"call-http-agent-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		build_final_answer,
	))

	assembly=build_agent_diagnosis_assembly(
		provider,
		"mock",
		(build_thread_pool_tool(),),
		"order-service",
	)

	return create_app(assembly)


def build_openai_agent_app(
	base_url:str,
	api_key:str,
	model:str,
):
	model_timeout_seconds=float(
		os.getenv("EVIDENCEOPS_MODEL_TIMEOUT_SECONDS","60.0")
	)

	provider=OpenAICompatibleProvider(
		base_url=base_url,
		api_key=api_key,
	)

	assembly=build_agent_diagnosis_assembly(
		provider,
		"openai-compatible",
		(build_thread_pool_tool(),),
		"order-service",
		model=model,
		model_timeout_seconds=model_timeout_seconds,
	)

	return create_app(assembly)


def build_configured_agent_app():
	provider_mode=os.getenv(
		"EVIDENCEOPS_PROVIDER",
		"mock",
	).strip().lower()

	if provider_mode=="mock":
		return build_agent_app()

	if provider_mode!="openai-compatible":
		raise ValueError(
			"EVIDENCEOPS_PROVIDER必须是mock或openai-compatible"
		)

	base_url=os.getenv("EVIDENCEOPS_MODEL_BASE_URL")
	api_key=os.getenv("EVIDENCEOPS_MODEL_API_KEY")
	model=os.getenv("EVIDENCEOPS_MODEL_NAME")

	if not base_url or not api_key or not model:
		raise ValueError(
			"openai-compatible模式必须配置"
			"EVIDENCEOPS_MODEL_BASE_URL、"
			"EVIDENCEOPS_MODEL_API_KEY、"
			"EVIDENCEOPS_MODEL_NAME"
		)

	return build_openai_agent_app(
		base_url=base_url,
		api_key=api_key,
		model=model,
	)


app=build_configured_agent_app()
