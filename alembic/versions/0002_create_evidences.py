from alembic import op
import sqlalchemy as sa


revision="0002"
down_revision="0001"
branch_labels=None
depends_on=None


def upgrade()->None:
	op.create_table(
		"evidences",
		sa.Column("evidence_id",sa.Text(),nullable=False),
		sa.Column("run_id",sa.Text(),nullable=False),
		sa.Column("source",sa.Text(),nullable=False),
		sa.Column("observed_at",sa.DateTime(timezone=True),nullable=False),
		sa.Column("summary",sa.Text(),nullable=False),
		sa.Column("source_ref",sa.Text(),nullable=False),
		sa.Column("content_hash",sa.Text(),nullable=False),
		sa.Column("source_version",sa.Text(),nullable=True),
		sa.ForeignKeyConstraint(
			["run_id"],
			["diagnosis_runs.run_id"],
			name="fk_evidences_run_id",
		),
		sa.PrimaryKeyConstraint("evidence_id",name="pk_evidences"),
		sa.CheckConstraint(
			"source IN ('log','metric','config')",
			name="ck_evidences_source",
		),
	)
	op.create_index("ix_evidences_run_id_observed_at","evidences",["run_id","observed_at"])


def downgrade()->None:
	op.drop_index("ix_evidences_run_id_observed_at",table_name="evidences")
	op.drop_table("evidences")
