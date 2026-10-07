import json
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine,select
from sqlalchemy.orm import Session,sessionmaker

from evidenceops.application.execution_record import ExecutionRecord
from evidenceops.infrastructure.database.models import ExecutionRecordRow
from evidenceops.infrastructure.database.session import transaction_scope


class SqlAlchemyExecutionRecordRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def create_many(self,run_id:str,records:tuple[ExecutionRecord,...])->None:
		for record in records:
			row=ExecutionRecordRow(
				run_id=run_id,
				kind=record.kind,
				model_round=record.model_round,
				model_request_id=record.model_request_id,
				tool_name=record.tool_name,
				tool_call_id=record.tool_call_id,
				started_at=record.started_at,
				finished_at=record.finished_at,
				duration_ms=record.duration_ms,
				status=record.status,
				error_code=record.error_code,
				handler_started_at=record.handler_started_at,
				handler_finished_at=record.handler_finished_at,
				query_arguments=json.dumps(record.query_arguments) if record.query_arguments is not None else None,
			)
			self._session.add(row)
		self._session.flush()

	def list_by_run(self,run_id:str)->tuple[ExecutionRecord,...]:
		statement=select(ExecutionRecordRow).where(
			ExecutionRecordRow.run_id==run_id,
		).order_by(
			ExecutionRecordRow.started_at,
			ExecutionRecordRow.record_id,
		)
		return tuple(self._to_record(row) for row in self._session.scalars(statement).all())

	@staticmethod
	def _to_record(row:ExecutionRecordRow)->ExecutionRecord:
		return ExecutionRecord(
			kind=row.kind,
			started_at=row.started_at,
			finished_at=row.finished_at,
			duration_ms=row.duration_ms,
			status=row.status,
			error_code=row.error_code,
			run_id=row.run_id,
			model_round=row.model_round,
			model_request_id=row.model_request_id,
			tool_name=row.tool_name,
			tool_call_id=row.tool_call_id,
			handler_started_at=row.handler_started_at,
			handler_finished_at=row.handler_finished_at,
			query_arguments=json.loads(row.query_arguments) if row.query_arguments is not None else None,
		)


class SqlAlchemyExecutionRecordPersistence:
	def __init__(self,session_factory:sessionmaker[Session],engine:Engine|None=None)->None:
		self._session_factory=session_factory
		self._engine=engine

	@contextmanager
	def transaction(self)->Iterator[SqlAlchemyExecutionRecordRepository]:
		with transaction_scope(self._session_factory) as session:
			yield SqlAlchemyExecutionRecordRepository(session)

	def close(self)->None:
		if self._engine is not None:
			self._engine.dispose()
