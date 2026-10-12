"""负责 SQLAlchemy 诊断事务、仓储组装及 PostgreSQL 实例锁的生命周期。"""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock

from sqlalchemy import Engine,text
from sqlalchemy.orm import Session,sessionmaker

from evidenceops.application.diagnosis_persistence import DiagnosisTransaction
from evidenceops.infrastructure.database.evidence_repository import SqlAlchemyEvidenceRepository
from evidenceops.infrastructure.database.execution_record_repository import SqlAlchemyExecutionRecordRepository
from evidenceops.infrastructure.database.report_repository import SqlAlchemyReportRepository
from evidenceops.infrastructure.database.run_repository import SqlAlchemyRunRepository
from evidenceops.infrastructure.database.trace_event_repository import SqlAlchemyTraceEventRepository
from evidenceops.infrastructure.database.session import transaction_scope


INSTANCE_LOCK_KEY=(1163284304,1)


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
		self._instance_connection=None
		self._instance_guard=RLock()
		self._lock_lost=False
		self._lock_key=INSTANCE_LOCK_KEY

	def acquire_instance_lock(self)->None:
		# PostgreSQL 使用会话级锁；生产 SQLite 的文件锁由 LocalPersistence 负责。
		bind=self._engine or self._session_factory.kw.get("bind")
		if bind.dialect.name!="postgresql":
			return
		if self._engine is None:
			raise RuntimeError("PostgreSQL实例锁需要独立Engine")
		with self._instance_guard:
			if self._instance_connection is not None:
				self._check_instance_lock()
				return
			connection=self._engine.connect()
			try:
				acquired=connection.scalar(text("SELECT pg_try_advisory_lock(:namespace,:identity)"),
					{"namespace":self._lock_key[0],"identity":self._lock_key[1]})
				connection.commit()
				if not acquired:
					raise RuntimeError("另一个EvidenceOps实例正在使用此数据库；拒绝启动")
			except BaseException:

				connection.invalidate()
				connection.close()
				raise
			self._instance_connection=connection
			self._lock_lost=False

	def _check_instance_lock(self)->None:
		with self._instance_guard:
			if self._lock_lost:
				raise RuntimeError("实例锁连接已丢失；必须重启服务")
			connection=self._instance_connection
			if connection is None:
				return
			try:

				if connection.closed or connection.invalidated:
					raise RuntimeError("实例锁连接失效")
				connection.execute(text("SELECT 1"))
				connection.rollback()
			except BaseException:
				self._lock_lost=True
				raise

	@contextmanager
	def transaction(self)->Iterator[DiagnosisTransaction]:
		self._check_instance_lock()

		with transaction_scope(self._session_factory) as session:
			yield SqlAlchemyDiagnosisTransaction(
				run=SqlAlchemyRunRepository(session),
				evidence=SqlAlchemyEvidenceRepository(session),
				report=SqlAlchemyReportRepository(session),
				execution_record=SqlAlchemyExecutionRecordRepository(session),
				trace_event=SqlAlchemyTraceEventRepository(session),
			)

	def close(self)->None:
		with self._instance_guard:
			connection=self._instance_connection
			self._instance_connection=None
			try:
				if connection is not None:
					try:
						if not connection.closed and not connection.invalidated:
							connection.execute(text("SELECT pg_advisory_unlock(:namespace,:identity)"),
								{"namespace":self._lock_key[0],"identity":self._lock_key[1]})
							connection.commit()
					finally:
						connection.invalidate()
						connection.close()
			finally:
				if self._engine is not None:
					self._engine.dispose()
