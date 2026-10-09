from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus


@dataclass(frozen=True,slots=True)
class RunRecord:
	run_id:str
	request_id:str
	description:str
	status:RunStatus
	created_at:datetime
	started_at:datetime|None
	finished_at:datetime|None
	error_code:str|None


class RunRepository(Protocol):
	def create(self,run:DiagnosisRun)->None:
		...

	def update(self,run:DiagnosisRun)->None:
		...

	def get(self,run_id:str)->RunRecord|None:
		...


class RunPersistence(Protocol):
	def transaction(self)->AbstractContextManager[RunRepository]:
		...


class RunPersistenceError(RuntimeError):
	error_code="RUN_PERSISTENCE_FAILED"

	def __init__(self,operation:str,run_id:str)->None:
		self.operation=operation
		self.run_id=run_id
		super().__init__(f"Run持久化失败:operation={operation},run_id={run_id}")
