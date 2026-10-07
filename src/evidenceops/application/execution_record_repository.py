from contextlib import AbstractContextManager
from typing import Protocol

from evidenceops.application.execution_record import ExecutionRecord


class ExecutionRecordRepository(Protocol):
	def create_many(self,run_id:str,records:tuple[ExecutionRecord,...])->None:
		...

	def list_by_run(self,run_id:str)->tuple[ExecutionRecord,...]:
		...


class ExecutionRecordPersistence(Protocol):
	def transaction(self)->AbstractContextManager[ExecutionRecordRepository]:
		...
