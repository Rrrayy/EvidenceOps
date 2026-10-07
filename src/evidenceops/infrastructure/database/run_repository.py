from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session,sessionmaker

from evidenceops.application.run_repository import RunRecord
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.infrastructure.database.models import RunRow
from evidenceops.infrastructure.database.session import transaction_scope


class SqlAlchemyRunRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def create(self,run:DiagnosisRun)->None:
		row=RunRow(
			run_id=run.run_id,
			request_id=run.request_id,
			description=run.description,
			status=run.status.value,
			created_at=run.created_at,
			started_at=run.started_at,
			finished_at=run.finished_at,
			error_code=run.error_code,
		)
		self._session.add(row)
		self._session.flush()

	def update(self,run:DiagnosisRun)->None:
		row=self._session.get(RunRow,run.run_id)

		if row is None:
			raise LookupError(f"数据库中不存在Run:{run.run_id}")

		row.status=run.status.value
		row.started_at=run.started_at
		row.finished_at=run.finished_at
		row.error_code=run.error_code
		self._session.flush()

	def get(self,run_id:str)->RunRecord|None:
		if not isinstance(run_id,str) or not run_id.strip():
			raise ValueError("run_id不能为空")

		row=self._session.get(RunRow,run_id)

		if row is None:
			return None

		try:
			status=RunStatus(row.status)
		except ValueError as error:
			raise RuntimeError(f"数据库中的Run状态无效:{row.status}") from error

		return RunRecord(
			run_id=row.run_id,
			request_id=row.request_id,
			description=row.description,
			status=status,
			created_at=row.created_at,
			started_at=row.started_at,
			finished_at=row.finished_at,
			error_code=row.error_code,
		)


class SqlAlchemyRunPersistence:
	def __init__(
		self,
		session_factory:sessionmaker[Session],
		engine:Engine|None=None,
	)->None:
		self._session_factory=session_factory
		self._engine=engine

	@contextmanager
	def transaction(self)->Iterator[SqlAlchemyRunRepository]:
		with transaction_scope(self._session_factory) as session:
			yield SqlAlchemyRunRepository(session)

	def close(self)->None:
		if self._engine is not None:
			self._engine.dispose()