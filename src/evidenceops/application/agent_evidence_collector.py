from evidenceops.application.agent_collection_result import (
	AgentCollectionError,
	AgentCollectionResult,
)
from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.application.model_protocol import StructuredFinalAnswer
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence


class AgentEvidenceCollector:
	def __init__(self,agent_loop:AgentLoop,tool_collector:ToolEvidenceCollector)->None:
		self._agent_loop=agent_loop
		self._tool_collector=tool_collector

	def collect(self,run:DiagnosisRun)->AgentCollectionResult:
		loop_result=self._agent_loop.run(
			run.description,
			run_id=run.run_id,
		)

		if loop_result.error_code is not None:
			raise AgentCollectionError(
				loop_result.error_code,
				loop_result.error_message or "Agent Loop执行失败",
			)

		evidences=[]

		for tool_result in loop_result.tool_results:
			evidences.append(
				self._tool_collector.collect_result(run,tool_result)
			)

		if not isinstance(
			loop_result.final_answer,
			StructuredFinalAnswer,
		):
			raise AgentCollectionError(
				"MODEL_PROTOCOL_ERROR",
				"模型没有返回结构化最终答案",
			)

		try:
			draft=DiagnosisDraft.from_mapping(
				loop_result.final_answer.data
			)
		except Exception as error:
			raise AgentCollectionError(
				"MODEL_PROTOCOL_ERROR",
				f"结构化最终答案无法转换为DiagnosisDraft：{error}",
			) from error

		return AgentCollectionResult(
			evidences=tuple(evidences),
			draft=draft,
		)
