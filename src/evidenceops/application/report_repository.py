from contextlib import AbstractContextManager
from typing import Protocol

from evidenceops.domain.diagnosis_report import DiagnosisReport


class ReportRepository(Protocol):
	def create(self,report:DiagnosisReport)->None:
		...

	def get(self,run_id:str)->DiagnosisReport|None:
		...


class ReportPersistence(Protocol):
	def transaction(self)->AbstractContextManager[ReportRepository]:
		...
