from alembic import op
import sqlalchemy as sa


revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None


def upgrade()->None:
	op.create_table(
		"diagnosis_reports",
		sa.Column("run_id",sa.Text(),nullable=False),
		sa.Column("root_cause_text",sa.Text(),nullable=False),
		sa.Column("root_cause_evidence_ids",sa.Text(),nullable=False),
		sa.Column("recommendations",sa.Text(),nullable=False),
		sa.Column("confidence",sa.Float(),nullable=False),
		sa.Column("limitations",sa.Text(),nullable=False),
		sa.ForeignKeyConstraint(["run_id"],["diagnosis_runs.run_id"],name="fk_diagnosis_reports_run_id"),
		sa.PrimaryKeyConstraint("run_id",name="pk_diagnosis_reports"),
	)
	op.create_table(
		"execution_records",
		sa.Column("record_id",sa.Integer(),autoincrement=True,nullable=False),
		sa.Column("run_id",sa.Text(),nullable=False),
		sa.Column("kind",sa.Text(),nullable=False),
		sa.Column("model_round",sa.Integer(),nullable=True),
		sa.Column("model_request_id",sa.Text(),nullable=True),
		sa.Column("tool_name",sa.Text(),nullable=True),
		sa.Column("tool_call_id",sa.Text(),nullable=True),
		sa.Column("started_at",sa.DateTime(timezone=True),nullable=False),
		sa.Column("finished_at",sa.DateTime(timezone=True),nullable=False),
		sa.Column("duration_ms",sa.Float(),nullable=False),
		sa.Column("status",sa.Text(),nullable=False),
		sa.Column("error_code",sa.Text(),nullable=True),
		sa.Column("handler_started_at",sa.DateTime(timezone=True),nullable=True),
		sa.Column("handler_finished_at",sa.DateTime(timezone=True),nullable=True),
		sa.Column("query_arguments",sa.Text(),nullable=True),
		sa.ForeignKeyConstraint(["run_id"],["diagnosis_runs.run_id"],name="fk_execution_records_run_id"),
		sa.PrimaryKeyConstraint("record_id",name="pk_execution_records"),
	)
	op.create_index("ix_execution_records_run_id_started_at","execution_records",["run_id","started_at"])


def downgrade()->None:
	op.drop_index("ix_execution_records_run_id_started_at",table_name="execution_records")
	op.drop_table("execution_records")
	op.drop_table("diagnosis_reports")
