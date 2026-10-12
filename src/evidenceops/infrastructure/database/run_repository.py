"""负责诊断运行记录和运行时模型快照的数据库读写。"""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine,select
from sqlalchemy.orm import Session,sessionmaker

from evidenceops.application.run_repository import RunRecord
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.infrastructure.database.models import RunRow
from evidenceops.infrastructure.database.session import transaction_scope


class SqlAlchemyRunRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def list_recent(self,limit:int=20,offset:int=0,status:str|None=None,search:str="")->tuple[RunRecord,...]:

		if not 1<=limit<=101 or offset<0:
			raise ValueError("历史分页参数无效")
		query=select(RunRow)

		if status is not None:
			query=query.where(RunRow.status==status)
		if search:
			query=query.where(RunRow.description.contains(search,autoescape=True)|RunRow.run_id.contains(search,autoescape=True))
		rows=self._session.scalars(query.order_by(RunRow.created_at.desc(),RunRow.run_id.desc()).offset(offset).limit(limit))

		return tuple(RunRecord(row.run_id,row.request_id,row.description,RunStatus(row.status),row.created_at,row.started_at,row.finished_at,row.error_code) for row in rows)

	def list_unfinished(self,limit:int=100)->tuple[str,...]:
		query=select(RunRow.run_id).where(RunRow.status.in_(("pending","running")))
		return tuple(self._session.scalars(query.order_by(RunRow.created_at,RunRow.run_id).limit(limit)))

	def mark_interrupted(self,run_id:str,finished_at,error_code:str)->bool:

		row=self._session.scalar(select(RunRow).where(RunRow.run_id==run_id).with_for_update())
		if row is None or row.status not in ("pending","running"):
			return False
		row.status="failed"
		row.finished_at=finished_at
		row.error_code=error_code
		self._session.flush()
		return True

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

	def save_model(self,run_id,model_config):
		row=self._session.get(RunRow,run_id)
		if row is None: raise LookupError("诊断运行不存在")
		row.model_config=dict(model_config) if model_config else None
		self._session.flush()

	def load_model(self,run_id):
		row=self._session.get(RunRow,run_id)
		return row.model_config if row is not None else None

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
	def __init__(self,session_factory:sessionmaker[Session],engine:Engine|None=None)->None:
		self._session_factory=session_factory
		self._engine=engine

	@contextmanager
	def transaction(self)->Iterator[SqlAlchemyRunRepository]:
		with transaction_scope(self._session_factory) as session:
			yield SqlAlchemyRunRepository(session)

	def close(self)->None:
		if self._engine is not None:
			self._engine.dispose()
