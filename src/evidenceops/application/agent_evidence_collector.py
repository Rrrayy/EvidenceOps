from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence


class AgentEvidenceCollector:
	def __init__(self,agent_loop:AgentLoop,tool_collector:ToolEvidenceCollector)->None:
		self._agent_loop=agent_loop
		self._tool_collector=tool_collector

	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:
		loop_result=self._agent_loop.run(
			run.description,
			run_id=run.run_id,
		)

		if loop_result.error_code is not None:
			raise RuntimeError(
				f"{loop_result.error_code}:Agent Loop执行失败"
			)

		evidences=[]

		for tool_result in loop_result.tool_results:
			evidences.append(
				self._tool_collector.collect_result(run,tool_result)
			)

		return tuple(evidences)