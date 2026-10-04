from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from evidenceops.application.agent_collection_result import (
	AgentCollectionError,
	AgentCollectionResult,
)
from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.domain.diagnosis_report import (
	DiagnosisReport,
	validate_report_evidence,
)
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.domain.evidence import Evidence


class EvidenceCollector(Protocol):
	def collect(
		self,
		run:DiagnosisRun,
	)->tuple[Evidence,...]|AgentCollectionResult:
		...


class ReportGenerator(Protocol):
	def generate(
		self,
		run:DiagnosisRun,
		evidences:tuple[Evidence,...],
		*draft:DiagnosisDraft,
	)->DiagnosisReport:
		...


@dataclass(frozen=True,slots=True)
class DiagnosisExecution:
	run:DiagnosisRun
	evidences:tuple[Evidence,...]
	report:DiagnosisReport|None
	error_detail:dict[str,str]|None


class DiagnosisService:
	def __init__(
		self,
		evidence_collector:EvidenceCollector,
		report_generator:ReportGenerator,
		run_id_factory:Callable[[],str]|None=None,
	)->None:
		self._evidence_collector=evidence_collector
		self._report_generator=report_generator
		self._run_id_factory=run_id_factory or (lambda:f"run-{uuid4()}")

	def execute(
		self,
		request_id:str,
		description:str,
	)->DiagnosisExecution:
		run=DiagnosisRun(
			self._run_id_factory(),
			request_id,
			description,
		)
		run.transition(RunStatus.RUNNING)

		evidences:tuple[Evidence,...]=()
		draft:DiagnosisDraft|None=None

		try:
			collection=self._evidence_collector.collect(run)

			if isinstance(collection,AgentCollectionResult):
				evidences=collection.evidences
				draft=collection.draft
			else:
				evidences=tuple(collection)

			self._validate_collected_evidences(run,evidences)

		except AgentCollectionError as error:
			run.transition(
				RunStatus.FAILED,
				error_code=error.error_code,
			)
			return DiagnosisExecution(
				run,
				evidences,
				None,
				{
					"code":error.error_code,
					"message":error.error_message,
				},
			)

		except ToolCollectionError as error:
			run.transition(
				RunStatus.FAILED,
				error_code="EVIDENCE_COLLECTION_FAILED",
			)
			return DiagnosisExecution(
				run,
				evidences,
				None,
				{
					"code":error.error_code,
					"message":error.error_message,
				},
			)

		except Exception:
			run.transition(
				RunStatus.FAILED,
				error_code="EVIDENCE_COLLECTION_FAILED",
			)
			return DiagnosisExecution(
				run,
				evidences,
				None,
				None,
			)

		if not evidences:
			run.transition(
				RunStatus.FAILED,
				error_code="EVIDENCE_INSUFFICIENT",
			)
			return DiagnosisExecution(
				run,
				evidences,
				None,
				None,
			)

		if draft is not None:
			try:
				self._validate_draft_evidence(draft,evidences)
			except ValueError:
				run.transition(
					RunStatus.FAILED,
					error_code="INVALID_REPORT_EVIDENCE",
				)
				return DiagnosisExecution(run,evidences,None,{
					"code":"INVALID_REPORT_EVIDENCE",
					"message":"Draft引用的证据无效",
				})

		try:
			if draft is None:
				report=self._report_generator.generate(
					run,
					evidences,
				)
			else:
				report=self._report_generator.generate(
					run,
					evidences,
					draft,
				)

		except Exception:
			run.transition(
				RunStatus.FAILED,
				error_code="REPORT_GENERATION_FAILED",
			)
			return DiagnosisExecution(
				run,
				evidences,
				None,
				{
					"code":"REPORT_GENERATION_FAILED",
					"message":"报告生成器执行失败",
				},
			)

		try:
			validate_report_evidence(report,evidences)

		except Exception:
			run.transition(
				RunStatus.FAILED,
				error_code="INVALID_REPORT_EVIDENCE",
			)
			return DiagnosisExecution(
				run,
				evidences,
				None,
				{
					"code":"INVALID_REPORT_EVIDENCE",
					"message":"报告引用的证据无效",
				},
			)

		run.transition(RunStatus.SUCCEEDED)

		return DiagnosisExecution(
			run,
			evidences,
			report,
			None,
		)

	@staticmethod
	def _validate_collected_evidences(
		run:DiagnosisRun,
		evidences:tuple[Evidence,...],
	)->None:
		seen_ids:set[str]=set()

		for evidence in evidences:
			if not isinstance(evidence,Evidence):
				raise TypeError(
					"collector必须返回Evidence对象"
				)

			if evidence.run_id!=run.run_id:
				raise ValueError(
					"Evidence不属于当前运行"
				)

			if evidence.evidence_id in seen_ids:
				raise ValueError(
					"Evidence ID不能重复"
				)

			seen_ids.add(evidence.evidence_id)

	@staticmethod
	def _validate_draft_evidence(
		draft:DiagnosisDraft,
		evidences:tuple[Evidence,...],
	)->None:
		evidence_ids={evidence.evidence_id for evidence in evidences}
		referenced_ids=set(draft.root_cause.evidence_ids)

		for recommendation in draft.recommendations:
			referenced_ids.update(recommendation.evidence_ids)

		if not referenced_ids.issubset(evidence_ids):
			raise ValueError("Draft引用了当前运行不存在的Evidence")
