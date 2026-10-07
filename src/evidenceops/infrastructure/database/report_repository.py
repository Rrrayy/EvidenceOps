import json
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session,sessionmaker

from evidenceops.application.report_repository import ReportRepository
from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport
from evidenceops.infrastructure.database.models import DiagnosisReportRow
from evidenceops.infrastructure.database.session import transaction_scope


class SqlAlchemyReportRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def create(self,report:DiagnosisReport)->None:
		row=DiagnosisReportRow(
			run_id=report.run_id,
			root_cause_text=report.root_cause.text,
			root_cause_evidence_ids=json.dumps(report.root_cause.evidence_ids),
			recommendations=json.dumps([
				{"text":claim.text,"evidence_ids":claim.evidence_ids}
				for claim in report.recommendations
			]),
			confidence=report.confidence,
			limitations=report.limitations,
		)
		self._session.add(row)
		self._session.flush()

	def get(self,run_id:str)->DiagnosisReport|None:
		row=self._session.get(DiagnosisReportRow,run_id)
		if row is None:
			return None

		root_cause=DiagnosisClaim(
			row.root_cause_text,
			tuple(json.loads(row.root_cause_evidence_ids)),
		)
		recommendations=tuple(
			DiagnosisClaim(item["text"],tuple(item["evidence_ids"]))
			for item in json.loads(row.recommendations)
		)
		return DiagnosisReport(
			row.run_id,
			root_cause,
			recommendations,
			row.confidence,
			row.limitations,
		)


class SqlAlchemyReportPersistence:
	def __init__(self,session_factory:sessionmaker[Session],engine:Engine|None=None)->None:
		self._session_factory=session_factory
		self._engine=engine

	@contextmanager
	def transaction(self)->Iterator[SqlAlchemyReportRepository]:
		with transaction_scope(self._session_factory) as session:
			yield SqlAlchemyReportRepository(session)

	def close(self)->None:
		if self._engine is not None:
			self._engine.dispose()
