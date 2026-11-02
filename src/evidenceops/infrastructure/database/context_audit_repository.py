"""在调用方事务中幂等保存上下文审计，不保存消息正文。"""
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from evidenceops.application.context_assembler import ContextAssembly
from evidenceops.infrastructure.database.models import ModelContextAuditRow


class ContextAuditRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def record(self,run_id:str,model_round:int,model_request_id:str,assembly:ContextAssembly)->None:
		dialect=self._session.get_bind().dialect.name
		if dialect not in ("sqlite","postgresql"):
			raise ValueError("上下文审计仅支持SQLite和PostgreSQL")
		insert=sqlite_insert if dialect=="sqlite" else postgres_insert
		# 唯一键冲突在数据库内处理，避免并发重放时先查后插发生竞争。
		statement=insert(ModelContextAuditRow).values(
			run_id=run_id,model_round=model_round,model_request_id=model_request_id,
			payload_hash=assembly.reservation.payload_hash,estimator_id=assembly.estimator_id,
			estimated_input_tokens=assembly.estimated_input_tokens,
			reserved_output_tokens=assembly.reservation.max_output_tokens,
			visible_evidence_ids=list(assembly.visible_evidence_ids),
			deduplication_map=assembly.deduplication_map,omissions=list(assembly.omissions),
		).on_conflict_do_nothing(index_elements=["run_id","model_request_id"])
		self._session.execute(statement)
