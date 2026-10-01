from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.domain.diagnosis_report import DiagnosisReport,validate_report_evidence
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.domain.evidence import Evidence


class EvidenceCollector(Protocol):
	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:
		...


class ReportGenerator(Protocol):
	def generate(self,run:DiagnosisRun,evidences:tuple[Evidence,...])->DiagnosisReport:
		...


@dataclass(frozen=True,slots=True)
class DiagnosisExecution:
	run:DiagnosisRun
	evidences:tuple[Evidence,...]
	report:DiagnosisReport|None
	error_detail:dict[str,str]|None


class DiagnosisService:
	def __init__(self,evidence_collector:EvidenceCollector,report_generator:ReportGenerator,run_id_factory:Callable[[],str]|None=None)->None:
		self._evidence_collector=evidence_collector
		self._report_generator=report_generator
		self._run_id_factory=run_id_factory or (lambda:f"run-{uuid4()}")

	def execute(self,request_id:str,description:str)->DiagnosisExecution:
		run=DiagnosisRun(self._run_id_factory(),request_id,description)
		run.transition(RunStatus.RUNNING)
		evidences:tuple[Evidence,...]=()

		try:
			evidences=tuple(self._evidence_collector.collect(run))
			self._validate_collected_evidences(run,evidences)

		except ToolCollectionError as error:
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_COLLECTION_FAILED")
			return DiagnosisExecution(run,evidences,None,{
				"code":error.error_code,
				"message":error.error_message,
			})

		except Exception:
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_COLLECTION_FAILED")
			return DiagnosisExecution(run,evidences,None,None)

		if not evidences:
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_INSUFFICIENT")
			return DiagnosisExecution(run,evidences,None,None)

		try:
			report=self._report_generator.generate(run,evidences)

		except Exception:
			run.transition(RunStatus.FAILED,error_code="REPORT_GENERATION_FAILED")
			return DiagnosisExecution(run,evidences,None,{
				"code":"REPORT_GENERATION_FAILED",
				"message":"报告生成器执行失败",
			})

		try:
			validate_report_evidence(report,evidences)

		except Exception:
			run.transition(RunStatus.FAILED,error_code="INVALID_REPORT_EVIDENCE")
			return DiagnosisExecution(run,evidences,None,{
				"code":"INVALID_REPORT_EVIDENCE",
				"message":"报告引用的证据无效",
			})

		run.transition(RunStatus.SUCCEEDED)
		return DiagnosisExecution(run,evidences,report,None)

	@staticmethod
	def _validate_collected_evidences(run:DiagnosisRun,evidences:tuple[Evidence,...])->None:
		seen_ids:set[str]=set()

		for evidence in evidences:
			if not isinstance(evidence,Evidence):
				raise TypeError("collector必须返回Evidence对象")

			if evidence.run_id!=run.run_id:
				raise ValueError("Evidence不属于当前运行")

			if evidence.evidence_id in seen_ids:
				raise ValueError("Evidence ID不能重复")

			seen_ids.add(evidence.evidence_id)