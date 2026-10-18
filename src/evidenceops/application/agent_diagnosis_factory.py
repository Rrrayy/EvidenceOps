from dataclasses import dataclass

from evidenceops.application.agent_evidence_collector import AgentEvidenceCollector
from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.diagnosis_report_builder import DraftReportGenerator
from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.application.diagnosis_persistence import DiagnosisPersistence
from evidenceops.application.llm_gateway import LLMGateway
from evidenceops.application.model_protocol import ModelProvider
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.application.tool_runtime import ToolRuntime,ToolSpec
from evidenceops.application.token_budget import ContextConfig


@dataclass(slots=True)
class AgentDiagnosisAssembly:
	evidence_collector:AgentEvidenceCollector
	diagnosis_service:DiagnosisService
	runtime:ToolRuntime
	provider:ModelProvider
	diagnosis_persistence:DiagnosisPersistence|None=None
	tools:tuple=() # 每次运行复用声明，不修改共享 Provider。
	service_name:str="order-service" # 保留原 Connector 服务范围。
	model:str="mock-model" # 系统模型可读声明。
	provider_name:str="mock" # 供应商与模型分别记录。
	model_timeout_seconds:float=10 # 保留执行参数。
	max_steps:int=3 # 冻结执行步数。
	run_timeout_seconds:float|None=None # 保留运行预算。

	def close(self)->None:
		# 上层资源关闭失败也必须释放数据库会话锁，不能阻止下一实例启动。
		try:
			self.runtime.close()
		finally:
			try:
				close_provider=getattr(self.provider,"close",None)
				if callable(close_provider):
					close_provider()
			finally:
				close_persistence=getattr(self.diagnosis_persistence,"close",None)
				if callable(close_persistence):
					close_persistence()


def build_agent_diagnosis_assembly(
	provider:ModelProvider,
	provider_name:str,
	tools:tuple[ToolSpec,...],
	service_name:str,
	model:str="mock-model",
	model_timeout_seconds:float=10.0,
	tool_timeout_seconds:float=1.0,
	max_steps:int=3,
	response_format:str="json_object",
	diagnosis_persistence:DiagnosisPersistence|None=None,
	run_timeout_seconds:float|None=None,
	model_config:dict|None=None, # 本次冻结且无密钥的配置快照。
	context_config:ContextConfig|None=None,
	run_id_factory=None, # 管理服务预先固定 Run 身份。
)->AgentDiagnosisAssembly:
	runtime=ToolRuntime(tools,timeout_seconds=tool_timeout_seconds)

	gateway=LLMGateway(provider,provider_name)

	loop=AgentLoop(
		gateway,
		runtime,
		tools=tools,
		model=model,
		timeout_seconds=model_timeout_seconds,
		max_steps=max_steps,
		response_format=response_format,
		context_config=context_config,
	)

	tool_collector=ToolEvidenceCollector(runtime,service_name)
	evidence_collector=AgentEvidenceCollector(loop,tool_collector)
	report_generator=DraftReportGenerator()

	diagnosis_service=DiagnosisService(evidence_collector,report_generator,diagnosis_persistence=diagnosis_persistence,
		run_timeout_seconds=run_timeout_seconds,cancellation_enabled=True,model_config=model_config,run_id_factory=run_id_factory)

	return AgentDiagnosisAssembly(
		evidence_collector=evidence_collector,
		diagnosis_service=diagnosis_service,
		runtime=runtime,
		provider=provider,
		diagnosis_persistence=diagnosis_persistence,tools=tools,service_name=service_name,model=model,provider_name=provider_name,
		model_timeout_seconds=model_timeout_seconds,max_steps=max_steps,run_timeout_seconds=run_timeout_seconds,
	)
