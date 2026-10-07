from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from evidenceops.application.agent_collection_result import (
	AgentCollectionError,
	AgentCollectionResult,
)
from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.application.diagnosis_persistence import DiagnosisPersistence
from evidenceops.application.execution_record import ExecutionRecord
from evidenceops.application.run_repository import (
	RunPersistenceError,
)
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
	execution_records:tuple[ExecutionRecord,...]=()


class DiagnosisService:
	def __init__(
		self,
		evidence_collector:EvidenceCollector,
		report_generator:ReportGenerator,
		run_id_factory:Callable[[],str]|None=None,
		diagnosis_persistence:DiagnosisPersistence|None=None,
	)->None:
		self._evidence_collector=evidence_collector
		self._report_generator=report_generator
		self._run_id_factory=run_id_factory or (lambda:f"run-{uuid4()}")
		self._diagnosis_persistence=diagnosis_persistence

	def _persist_create(self,run:DiagnosisRun)->None:
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				transaction.run.create(run)
		except Exception as error:
			raise RunPersistenceError("create",run.run_id) from error

	def _persist_update(self,run:DiagnosisRun)->None:
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				transaction.run.update(run)
		except Exception as error:
			raise RunPersistenceError("update",run.run_id) from error

	def _transition_and_persist(
		self,
		run:DiagnosisRun,
		next_status:RunStatus,
		error_code:str|None=None,
	)->None:
		run.transition(next_status,error_code=error_code)
		self._persist_update(run)

	def _persist_success(
		self,
		run:DiagnosisRun,
		evidences:tuple[Evidence,...],
		report:DiagnosisReport,
		records:tuple[ExecutionRecord,...],
	)->None:
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				for evidence in evidences:
					transaction.evidence.create(evidence)
				transaction.report.create(report)
				transaction.execution_record.create_many(run.run_id,records)
				transaction.run.update(run)
		except Exception as error:
			raise RunPersistenceError("complete",run.run_id) from error

	def _persist_failure(
		self,
		run:DiagnosisRun,
		evidences:tuple[Evidence,...],
		records:tuple[ExecutionRecord,...],
	)->None:
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				for evidence in evidences:
					transaction.evidence.create(evidence)
				transaction.execution_record.create_many(run.run_id,records)
				transaction.run.update(run)
		except Exception as error:
			raise RunPersistenceError("fail",run.run_id) from error

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

		self._persist_create(run)
		self._transition_and_persist(run,RunStatus.RUNNING)

		records:tuple[ExecutionRecord,...]=()

		def finish(*args):
			return DiagnosisExecution(*args,execution_records=records)

		evidences:tuple[Evidence,...]=()
		draft:DiagnosisDraft|None=None

		try:
			collection=self._evidence_collector.collect(run)

			if isinstance(collection,AgentCollectionResult):
				records=collection.execution_records
				evidences=collection.evidences
				draft=collection.draft
			else:
				evidences=tuple(collection)

			self._validate_collected_evidences(run,evidences)

		except AgentCollectionError as error:
			records=error.execution_records
			run.transition(RunStatus.FAILED,error_code=error.error_code)
			self._persist_failure(run,evidences,records)
			return finish(
				run,
				evidences,
				None,
				{
					"code":error.error_code,
					"message":error.error_message,
				},
			)

		except ToolCollectionError as error:
			records=getattr(error,"execution_records",records)
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_COLLECTION_FAILED")
			self._persist_failure(run,evidences,records)
			return finish(
				run,
				evidences,
				None,
				{
					"code":error.error_code,
					"message":error.error_message,
				},
			)

		except Exception as error:
			records=getattr(error,"execution_records",records)
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_COLLECTION_FAILED")
			self._persist_failure(run,evidences,records)
			return finish(
				run,
				evidences,
				None,
				None,
			)

		if not evidences:
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_INSUFFICIENT")
			self._persist_failure(run,evidences,records)
			return finish(
				run,
				evidences,
				None,
				None,
			)

		if draft is not None:
			try:
				self._validate_draft_evidence(draft,evidences)
			except ValueError:
				run.transition(RunStatus.FAILED,error_code="INVALID_REPORT_EVIDENCE")
				self._persist_failure(run,evidences,records)
				return finish(
					run,
					evidences,
					None,
					{
						"code":"INVALID_REPORT_EVIDENCE",
						"message":"Draft引用的证据无效",
					},
				)

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
			run.transition(RunStatus.FAILED,error_code="REPORT_GENERATION_FAILED")
			self._persist_failure(run,evidences,records)
			return finish(
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
			run.transition(RunStatus.FAILED,error_code="INVALID_REPORT_EVIDENCE")
			self._persist_failure(run,evidences,records)
			return finish(
				run,
				evidences,
				None,
				{
					"code":"INVALID_REPORT_EVIDENCE",
					"message":"报告引用的证据无效",
				},
			)

		if self._diagnosis_persistence is None:
			self._transition_and_persist(run,RunStatus.SUCCEEDED)
		else:
			run.transition(RunStatus.SUCCEEDED)
			self._persist_success(run,evidences,report,records)

		return finish(
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
				raise TypeError("collector必须返回Evidence对象")

			if evidence.run_id!=run.run_id:
				raise ValueError("Evidence不属于当前运行")

			if evidence.evidence_id in seen_ids:
				raise ValueError("Evidence ID不能重复")

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
