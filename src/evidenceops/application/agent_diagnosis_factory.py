from dataclasses import dataclass

from evidenceops.application.agent_evidence_collector import AgentEvidenceCollector
from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.llm_gateway import LLMGateway
from evidenceops.application.model_protocol import ModelProvider
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.application.tool_runtime import ToolRuntime,ToolSpec


@dataclass(slots=True)
class AgentDiagnosisAssembly:
	evidence_collector:AgentEvidenceCollector
	runtime:ToolRuntime
	provider:ModelProvider

	def close(self)->None:
		self.runtime.close()

		close_provider=getattr(self.provider,"close",None)

		if callable(close_provider):
			close_provider()


def build_agent_diagnosis_assembly(
	provider:ModelProvider,
	provider_name:str,
	tools:tuple[ToolSpec,...],
	service_name:str,
	model:str="mock-model",
	model_timeout_seconds:float=10.0,
	tool_timeout_seconds:float=1.0,
	max_steps:int=3,
)->AgentDiagnosisAssembly:
	runtime=ToolRuntime(
		tools,
		timeout_seconds=tool_timeout_seconds,
	)

	gateway=LLMGateway(provider,provider_name)
	loop=AgentLoop(
		gateway,
		runtime,
		model=model,
		timeout_seconds=model_timeout_seconds,
		max_steps=max_steps,
	)
	tool_collector=ToolEvidenceCollector(runtime,service_name)
	evidence_collector=AgentEvidenceCollector(loop,tool_collector)

	return AgentDiagnosisAssembly(
		evidence_collector=evidence_collector,
		runtime=runtime,
		provider=provider,
	)
