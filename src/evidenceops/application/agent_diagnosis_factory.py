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


@dataclass(slots=True)
class AgentDiagnosisAssembly:
	evidence_collector:AgentEvidenceCollector
	diagnosis_service:DiagnosisService
	runtime:ToolRuntime
	provider:ModelProvider
	diagnosis_persistence:DiagnosisPersistence|None=None

	def close(self)->None:
		self.runtime.close()

		close_provider=getattr(self.provider,"close",None)

		if callable(close_provider):
			close_provider()

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
	)

	tool_collector=ToolEvidenceCollector(runtime,service_name)
	evidence_collector=AgentEvidenceCollector(loop,tool_collector)
	report_generator=DraftReportGenerator()

	diagnosis_service=DiagnosisService(evidence_collector,report_generator,diagnosis_persistence=diagnosis_persistence,
		run_timeout_seconds=run_timeout_seconds)

	return AgentDiagnosisAssembly(
		evidence_collector=evidence_collector,
		diagnosis_service=diagnosis_service,
		runtime=runtime,
		provider=provider,
		diagnosis_persistence=diagnosis_persistence,
	)
