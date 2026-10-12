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
	def list_recent(self,limit:int=20,offset:int=0,status:str|None=None,search:str="")->tuple[RunRecord,...]:
		# 控制台历史页使用有界查询，不执行模型。
		...

	def list_unfinished(self,limit:int=100)->tuple[str,...]:
		...

	def mark_interrupted(self,run_id:str,finished_at:datetime,error_code:str)->bool:
		...

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
