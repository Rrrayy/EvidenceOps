from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session,sessionmaker

from evidenceops.application.diagnosis_persistence import DiagnosisTransaction
from evidenceops.infrastructure.database.evidence_repository import SqlAlchemyEvidenceRepository
from evidenceops.infrastructure.database.execution_record_repository import SqlAlchemyExecutionRecordRepository
from evidenceops.infrastructure.database.report_repository import SqlAlchemyReportRepository
from evidenceops.infrastructure.database.run_repository import SqlAlchemyRunRepository
from evidenceops.infrastructure.database.trace_event_repository import SqlAlchemyTraceEventRepository
from evidenceops.infrastructure.database.session import transaction_scope


@dataclass(slots=True)
class SqlAlchemyDiagnosisTransaction:
	run:SqlAlchemyRunRepository
	evidence:SqlAlchemyEvidenceRepository
	report:SqlAlchemyReportRepository
	execution_record:SqlAlchemyExecutionRecordRepository
	trace_event:SqlAlchemyTraceEventRepository


class SqlAlchemyDiagnosisPersistence:
	def __init__(self,session_factory:sessionmaker[Session],engine:Engine|None=None)->None:
		self._session_factory=session_factory
		self._engine=engine

	@contextmanager
	def transaction(self)->Iterator[DiagnosisTransaction]:
		# 所有仓储共享一个 Session；仓储独立提交会破坏原子性。
		with transaction_scope(self._session_factory) as session:
			yield SqlAlchemyDiagnosisTransaction(
				run=SqlAlchemyRunRepository(session),
				evidence=SqlAlchemyEvidenceRepository(session),
				report=SqlAlchemyReportRepository(session),
				execution_record=SqlAlchemyExecutionRecordRepository(session),
				trace_event=SqlAlchemyTraceEventRepository(session),
			)

	def close(self)->None:
		if self._engine is not None:
			self._engine.dispose()
