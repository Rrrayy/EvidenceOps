"""定义诊断、报告、证据、执行记录和事件的数据库表，并统一 UTC 时间转换。"""
from datetime import datetime,timezone
from sqlalchemy.types import TypeDecorator

from sqlalchemy import BigInteger,CheckConstraint,DateTime,ForeignKey,Index,JSON,Text,UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column


class Base(DeclarativeBase):
	pass


class UTCDateTime(TypeDecorator):
	impl=DateTime
	cache_ok=True
	def load_dialect_impl(self,dialect): return dialect.type_descriptor(DateTime(timezone=True))
	def process_bind_param(self,value,dialect):
		if value is None: return None
		value=value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc) # 兼容已记录的 UTC 无时区字段。
		return value.replace(tzinfo=None) if dialect.name=="sqlite" else value # SQLite 写入规范的 UTC 墙钟。
	def process_result_value(self,value,dialect):
		return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value # 避免浏览器二次偏移。


class TraceEventRow(Base):
	__tablename__="trace_events"

	__table_args__=(UniqueConstraint("run_id","sequence",name="uq_trace_events_run_sequence"),
					CheckConstraint("sequence>0",name="ck_trace_events_sequence"),)
	event_id:Mapped[str]=mapped_column(Text,primary_key=True)
	run_id:Mapped[str]=mapped_column(Text,ForeignKey("diagnosis_runs.run_id",name="fk_trace_events_run_id"),nullable=False)
	sequence:Mapped[int]=mapped_column(BigInteger,nullable=False)
	event_type:Mapped[str]=mapped_column(Text,nullable=False)

	payload:Mapped[dict]=mapped_column(JSON().with_variant(JSONB(),"postgresql"),nullable=False)
	occurred_at:Mapped[datetime]=mapped_column(UTCDateTime(),nullable=False)


class RunRow(Base):
	__tablename__="diagnosis_runs"

	__table_args__=(
		CheckConstraint(
			"status IN ('pending','running','succeeded','failed','cancelled')",
			name="ck_diagnosis_runs_status",
		),
	)

	run_id:Mapped[str]=mapped_column(Text,primary_key=True)
	request_id:Mapped[str]=mapped_column(Text,nullable=False)
	description:Mapped[str]=mapped_column(Text,nullable=False)
	status:Mapped[str]=mapped_column(Text,nullable=False)
	created_at:Mapped[datetime]=mapped_column(UTCDateTime(),nullable=False)
	started_at:Mapped[datetime|None]=mapped_column(UTCDateTime(),nullable=True)
	finished_at:Mapped[datetime|None]=mapped_column(UTCDateTime(),nullable=True)
	error_code:Mapped[str|None]=mapped_column(Text,nullable=True)
	model_config:Mapped[dict|None]=mapped_column(JSON,nullable=True) # 历史实际模型与 Run 同库保存。


class EvidenceRow(Base):
	__tablename__="evidences"

	__table_args__=(
		CheckConstraint(
			"source IN ('log','metric','config','knowledge')",
			name="ck_evidences_source",
		),
		Index("ix_evidences_run_id_observed_at","run_id","observed_at"),
	)

	evidence_id:Mapped[str]=mapped_column(Text,primary_key=True)
	run_id:Mapped[str]=mapped_column(Text,ForeignKey("diagnosis_runs.run_id",name="fk_evidences_run_id"),nullable=False)
	source:Mapped[str]=mapped_column(Text,nullable=False)
	observed_at:Mapped[datetime]=mapped_column(UTCDateTime(),nullable=False)
	summary:Mapped[str]=mapped_column(Text,nullable=False)
	source_ref:Mapped[str]=mapped_column(Text,nullable=False)
	content_hash:Mapped[str]=mapped_column(Text,nullable=False)
	source_version:Mapped[str|None]=mapped_column(Text,nullable=True)
	content_snapshot:Mapped[str|None]=mapped_column(Text,nullable=True)
	source_metadata:Mapped[dict|None]=mapped_column(JSON().with_variant(JSONB(),"postgresql"),nullable=True)


class KnowledgeDocumentRow(Base):
	__tablename__="knowledge_documents"
	document_id:Mapped[str]=mapped_column(Text,primary_key=True)
	title:Mapped[str]=mapped_column(Text,nullable=False)
	source_ref:Mapped[str]=mapped_column(Text,nullable=False)


class KnowledgeVersionRow(Base):
	__tablename__="knowledge_versions"
	__table_args__=(UniqueConstraint("document_id","version_id",name="uq_knowledge_versions_document_version"),)
	version_id:Mapped[str]=mapped_column(Text,primary_key=True)
	document_id:Mapped[str]=mapped_column(Text,ForeignKey("knowledge_documents.document_id"),nullable=False)
	source_ref:Mapped[str]=mapped_column(Text,nullable=False)
	content:Mapped[str]=mapped_column(Text,nullable=False)
	content_hash:Mapped[str]=mapped_column(Text,nullable=False)
	status:Mapped[str]=mapped_column(Text,nullable=False,default="draft")


class KnowledgeChunkSetRow(Base):
	__tablename__="knowledge_chunk_sets"
	chunk_set_id:Mapped[str]=mapped_column(Text,primary_key=True)
	version_id:Mapped[str]=mapped_column(Text,ForeignKey("knowledge_versions.version_id"),nullable=False)
	algorithm_version:Mapped[str]=mapped_column(Text,nullable=False)
	chunk_size:Mapped[int]=mapped_column(nullable=False)
	chunk_overlap:Mapped[int]=mapped_column(nullable=False)


class KnowledgeChunkRow(Base):
	__tablename__="knowledge_chunks"
	__table_args__=(UniqueConstraint("chunk_set_id","chunk_index",name="uq_knowledge_chunks_set_index"),)
	chunk_id:Mapped[str]=mapped_column(Text,primary_key=True)
	chunk_set_id:Mapped[str]=mapped_column(Text,ForeignKey("knowledge_chunk_sets.chunk_set_id"),nullable=False)
	chunk_index:Mapped[int]=mapped_column(nullable=False)
	start_offset:Mapped[int]=mapped_column(nullable=False)
	end_offset:Mapped[int]=mapped_column(nullable=False)
	content:Mapped[str]=mapped_column(Text,nullable=False)
	content_hash:Mapped[str]=mapped_column(Text,nullable=False)
	heading_path:Mapped[list]=mapped_column(JSON().with_variant(JSONB(),"postgresql"),nullable=False)


class DiagnosisReportRow(Base):
	__tablename__="diagnosis_reports"

	run_id:Mapped[str]=mapped_column(
		Text,
		ForeignKey("diagnosis_runs.run_id",name="fk_diagnosis_reports_run_id"),
		primary_key=True,
	)
	root_cause_text:Mapped[str]=mapped_column(Text,nullable=False)
	root_cause_evidence_ids:Mapped[str]=mapped_column(Text,nullable=False)
	recommendations:Mapped[str]=mapped_column(Text,nullable=False)
	confidence:Mapped[float]=mapped_column(nullable=False)
	limitations:Mapped[str]=mapped_column(Text,nullable=False)


class ExecutionRecordRow(Base):
	__tablename__="execution_records"

	__table_args__=(Index("ix_execution_records_run_id_started_at","run_id","started_at"),)

	record_id:Mapped[int]=mapped_column(primary_key=True,autoincrement=True)
	run_id:Mapped[str]=mapped_column(
		Text,
		ForeignKey("diagnosis_runs.run_id",name="fk_execution_records_run_id"),
		nullable=False,
	)
	kind:Mapped[str]=mapped_column(Text,nullable=False)
	model_round:Mapped[int|None]=mapped_column(nullable=True)
	model_request_id:Mapped[str|None]=mapped_column(Text,nullable=True)
	tool_name:Mapped[str|None]=mapped_column(Text,nullable=True)
	tool_call_id:Mapped[str|None]=mapped_column(Text,nullable=True)
	started_at:Mapped[datetime]=mapped_column(UTCDateTime(),nullable=False)
	finished_at:Mapped[datetime]=mapped_column(UTCDateTime(),nullable=False)
	duration_ms:Mapped[float]=mapped_column(nullable=False)
	status:Mapped[str]=mapped_column(Text,nullable=False)
	error_code:Mapped[str|None]=mapped_column(Text,nullable=True)
	handler_started_at:Mapped[datetime|None]=mapped_column(UTCDateTime(),nullable=True)
	handler_finished_at:Mapped[datetime|None]=mapped_column(UTCDateTime(),nullable=True)
	query_arguments:Mapped[str|None]=mapped_column(Text,nullable=True)
