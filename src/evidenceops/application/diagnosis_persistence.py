from contextlib import AbstractContextManager
from typing import Protocol

from evidenceops.application.evidence_repository import EvidenceRepository
from evidenceops.application.execution_record_repository import ExecutionRecordRepository
from evidenceops.application.report_repository import ReportRepository
from evidenceops.application.run_repository import RunRepository
from evidenceops.application.trace_event_repository import TraceEventRepository


class DiagnosisTransaction(Protocol):
	run:RunRepository
	evidence:EvidenceRepository
	report:ReportRepository
	execution_record:ExecutionRecordRepository
	trace_event:TraceEventRepository


class DiagnosisPersistence(Protocol):
	def acquire_instance_lock(self)->None:
		...

	def transaction(self)->AbstractContextManager[DiagnosisTransaction]:
		...

	def close(self)->None:
		...
