from datetime import datetime

from sqlalchemy import CheckConstraint,DateTime,ForeignKey,Index,Text
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column


class Base(DeclarativeBase):
	pass


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
	created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
	started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
	finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
	error_code:Mapped[str|None]=mapped_column(Text,nullable=True)


class EvidenceRow(Base):
	__tablename__="evidences"

	__table_args__=(
		CheckConstraint(
			"source IN ('log','metric','config')",
			name="ck_evidences_source",
		),
		Index("ix_evidences_run_id_observed_at","run_id","observed_at"),
	)

	evidence_id:Mapped[str]=mapped_column(Text,primary_key=True)
	run_id:Mapped[str]=mapped_column(
		Text,
		ForeignKey("diagnosis_runs.run_id",name="fk_evidences_run_id"),
		nullable=False,
	)
	source:Mapped[str]=mapped_column(Text,nullable=False)
	observed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
	summary:Mapped[str]=mapped_column(Text,nullable=False)
	source_ref:Mapped[str]=mapped_column(Text,nullable=False)
	content_hash:Mapped[str]=mapped_column(Text,nullable=False)
	source_version:Mapped[str|None]=mapped_column(Text,nullable=True)


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

	__table_args__=(
		Index("ix_execution_records_run_id_started_at","run_id","started_at"),
	)

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
	started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
	finished_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
	duration_ms:Mapped[float]=mapped_column(nullable=False)
	status:Mapped[str]=mapped_column(Text,nullable=False)
	error_code:Mapped[str|None]=mapped_column(Text,nullable=True)
	handler_started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
	handler_finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
	query_arguments:Mapped[str|None]=mapped_column(Text,nullable=True)
