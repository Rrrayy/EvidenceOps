from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine,select
from sqlalchemy.orm import Session,sessionmaker

from evidenceops.application.evidence_repository import EvidenceRecord
from evidenceops.domain.evidence import Evidence
from evidenceops.infrastructure.database.models import EvidenceRow
from evidenceops.infrastructure.database.session import transaction_scope


class SqlAlchemyEvidenceRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def create(self,evidence:Evidence)->None:
		row=EvidenceRow(
			evidence_id=evidence.evidence_id,
			run_id=evidence.run_id,
			source=evidence.source.value,
			observed_at=evidence.observed_at,
			summary=evidence.summary,
			source_ref=evidence.source_ref,
			content_hash=evidence.content_hash,
			source_version=evidence.source_version,
		)
		self._session.add(row)
		self._session.flush()

	def get(self,evidence_id:str)->EvidenceRecord|None:
		if not isinstance(evidence_id,str) or not evidence_id.strip():
			raise ValueError("evidence_id不能为空")

		row=self._session.get(EvidenceRow,evidence_id)
		return None if row is None else self._to_record(row)

	def list_by_run(self,run_id:str)->tuple[EvidenceRecord,...]:
		if not isinstance(run_id,str) or not run_id.strip():
			raise ValueError("run_id不能为空")

		statement=select(EvidenceRow).where(
			EvidenceRow.run_id==run_id,
		).order_by(
			EvidenceRow.observed_at,
			EvidenceRow.evidence_id,
		)
		rows=self._session.scalars(statement).all()
		return tuple(self._to_record(row) for row in rows)

	@staticmethod
	def _to_record(row:EvidenceRow)->EvidenceRecord:
		return EvidenceRecord(
			evidence_id=row.evidence_id,
			run_id=row.run_id,
			source=row.source,
			observed_at=row.observed_at,
			summary=row.summary,
			source_ref=row.source_ref,
			content_hash=row.content_hash,
			source_version=row.source_version,
		)


class SqlAlchemyEvidencePersistence:
	def __init__(self,session_factory:sessionmaker[Session],engine:Engine|None=None)->None:
		self._session_factory=session_factory
		self._engine=engine

	@contextmanager
	def transaction(self)->Iterator[SqlAlchemyEvidenceRepository]:
		with transaction_scope(self._session_factory) as session:
			yield SqlAlchemyEvidenceRepository(session)

	def close(self)->None:
		if self._engine is not None:
			self._engine.dispose()
