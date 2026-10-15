"""负责组装模型 Provider、样例工具与诊断应用，并按配置选择持久化实现。"""
import os

from evidenceops.application.agent_diagnosis_factory import AgentDiagnosisAssembly,build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ModelRequest,StructuredFinalAnswer,ToolCall
from evidenceops.api.agent_diagnosis import create_app
from evidenceops.connectors.local_config import build_local_config_tool
from evidenceops.connectors.local_log import build_local_log_tool
from evidenceops.connectors.local_metric import build_local_metric_tool
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.infrastructure.providers.diagnosis_mock_provider import DiagnosisMockProvider
from evidenceops.infrastructure.providers.openai_compatible_provider import OpenAICompatibleProvider
from evidenceops.infrastructure.knowledge_tools import configured_knowledge_tools
_UNSET=object() # 安装管理可显式提供持久化，不改变开发入口配置。


def build_final_answer(request:ModelRequest)->StructuredFinalAnswer:
	evidence_ids=[f"{request.run_id}-{call_id}" for call_id in ("call-log-001","call-metric-001","call-config-001")]

	return StructuredFinalAnswer({
		"root_cause":{
			"text":"order-service出现RPC超时且同期线程池饱和、排队增加；故障时配置容量为64、RPC超时1000毫秒、最多额外重试2次，具体诱因尚未确认",
			"evidence_ids":evidence_ids,
		},
		"recommendations":[
			{
				"text":"检查order-service的线程池容量、任务执行耗时以及inventory-service的响应延迟",
				"evidence_ids":evidence_ids,
			},
		],
		"confidence":0.91,
		"limitations":"当前证据来自本地日志、指标和历史配置样本；配置允许重试不代表实际发生重试，尚缺调用链、流量和下游耗时，不能确认因果关系",
	})


def build_database_persistence()->SqlAlchemyDiagnosisPersistence|None:
	persistence_mode=os.getenv("EVIDENCEOPS_PERSISTENCE","memory").strip().lower()

	if persistence_mode=="memory":
		return None
	if persistence_mode=="sqlite":
		from evidenceops.infrastructure.local_storage import LocalPersistence,data_directory
		return LocalPersistence(data_directory()/"diagnosis.sqlite")

	if persistence_mode!="postgres":
		raise ValueError("EVIDENCEOPS_PERSISTENCE必须是memory、sqlite或postgres")

	settings=DatabaseSettings.from_environment()
	engine=create_database_engine(settings)
	session_factory=create_session_factory(engine)

	return SqlAlchemyDiagnosisPersistence(session_factory,engine)


def build_agent_app(diagnosis_persistence=_UNSET,connection_store=None)->object:
	provider=DiagnosisMockProvider((
		ToolCall(
			"call-log-001",
			"query_service_logs",
			{
				"service_name":"order-service",
				"environment":"production",
				"error_type":"rpc_timeout",
				"start_time":"2026-10-05T10:00:00+08:00",
				"end_time":"2026-10-05T10:10:00+08:00",
				"limit":50,
			},
		),
		ToolCall(
			"call-metric-001",
			"query_service_metrics",
			{
				"service_name":"order-service",
				"environment":"production",
				"start_time":"2026-10-05T10:00:00+08:00",
				"end_time":"2026-10-05T10:10:00+08:00",
				"limit":50,
			},
		),
		ToolCall(
			"call-config-001",
			"query_service_config",
			{
				"service_name":"order-service",
				"environment":"production",
				"at_time":"2026-10-05T10:02:00+08:00",
			},
		),
		build_final_answer,
	))

	tools=(build_local_log_tool(),build_local_metric_tool(),build_local_config_tool(),)

	if diagnosis_persistence is _UNSET: diagnosis_persistence=build_database_persistence()
	tools+=configured_knowledge_tools(diagnosis_persistence)

	assembly=build_agent_diagnosis_assembly(
		provider,
		"mock",
		tools,
		"order-service",
		max_steps=4,
		diagnosis_persistence=diagnosis_persistence,
		run_timeout_seconds=float(os.getenv("EVIDENCEOPS_RUN_TIMEOUT_SECONDS","180")),
	)

	from evidenceops.api.model_connections import ConnectionManager
	return create_app(assembly,ConnectionManager(assembly,connection_store))


def build_openai_agent_app(base_url:str,api_key:str,model:str,diagnosis_persistence=_UNSET,connection_store=None)->object:
	model_timeout_seconds=float(os.getenv("EVIDENCEOPS_MODEL_TIMEOUT_SECONDS","60.0"))

	provider=OpenAICompatibleProvider(base_url=base_url,api_key=api_key)

	tools=(build_local_log_tool(),build_local_metric_tool(),build_local_config_tool(),)

	if diagnosis_persistence is _UNSET: diagnosis_persistence=build_database_persistence()
	tools+=configured_knowledge_tools(diagnosis_persistence)

	assembly=build_agent_diagnosis_assembly(
		provider,
		"openai-compatible",
		tools,
		"order-service",
		model=model,
		model_timeout_seconds=model_timeout_seconds,
		max_steps=4,
		diagnosis_persistence=diagnosis_persistence,
		run_timeout_seconds=float(os.getenv("EVIDENCEOPS_RUN_TIMEOUT_SECONDS","180")),
	)

	from evidenceops.api.model_connections import ConnectionManager
	return create_app(assembly,ConnectionManager(assembly,connection_store))


def build_configured_agent_app(diagnosis_persistence=_UNSET,connection_store=None)->object:
	provider_mode=os.getenv("EVIDENCEOPS_PROVIDER","mock").strip().lower()

	if provider_mode=="mock":
		return build_agent_app(diagnosis_persistence,connection_store)

	if provider_mode!="openai-compatible":
		raise ValueError("EVIDENCEOPS_PROVIDER必须是mock或openai-compatible")

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

	return build_openai_agent_app(base_url=base_url,api_key=api_key,model=model,diagnosis_persistence=diagnosis_persistence,connection_store=connection_store)


class ConfiguredApp: # 导入工厂不创建数据库或读取客户模型配置。
	def __init__(self): self.application=None
	async def __call__(self,scope,receive,send):
		if self.application is None: self.application=build_configured_agent_app()
		await self.application(scope,receive,send)

app=ConfiguredApp()
