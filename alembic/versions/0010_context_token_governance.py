"""增加上下文审计、模型Token计量和Run汇总。"""
from alembic import op
import sqlalchemy as sa

revision="0010"
down_revision="0009"
branch_labels=None
depends_on=None


def upgrade():
	op.add_column("diagnosis_runs",sa.Column("token_summary",sa.JSON(),nullable=True))
	for name in ("estimated_input_tokens","reserved_output_tokens","reported_input_tokens","reported_output_tokens","reported_total_tokens"):
		op.add_column("execution_records",sa.Column(name,sa.Integer(),nullable=True))
	op.add_column("execution_records",sa.Column("usage_status",sa.Text(),nullable=True))
	op.add_column("execution_records",sa.Column("payload_hash",sa.Text(),nullable=True))
	op.create_table(
		"model_context_audits",
		sa.Column("audit_id",sa.Integer(),primary_key=True,autoincrement=True),
		sa.Column("run_id",sa.Text(),sa.ForeignKey("diagnosis_runs.run_id"),nullable=False),
		sa.Column("model_round",sa.Integer(),nullable=False),
		sa.Column("model_request_id",sa.Text(),nullable=False),
		sa.Column("payload_hash",sa.Text(),nullable=False),
		sa.Column("estimator_id",sa.Text(),nullable=False),
		sa.Column("estimated_input_tokens",sa.Integer(),nullable=False),
		sa.Column("reserved_output_tokens",sa.Integer(),nullable=False),
		sa.Column("visible_evidence_ids",sa.JSON(),nullable=False),
		sa.Column("deduplication_map",sa.JSON(),nullable=False),
		sa.Column("omissions",sa.JSON(),nullable=False),
	sa.UniqueConstraint("run_id","model_request_id",name="uq_context_audit_request"),
	)


def downgrade():
	op.drop_table("model_context_audits")
	for name in ("payload_hash","usage_status","reported_total_tokens","reported_output_tokens","reported_input_tokens","reserved_output_tokens","estimated_input_tokens"):
		op.drop_column("execution_records",name)
	op.drop_column("diagnosis_runs","token_summary")
