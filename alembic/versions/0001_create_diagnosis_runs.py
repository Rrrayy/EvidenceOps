from alembic import op
import sqlalchemy as sa


revision="0001"
down_revision=None
branch_labels=None
depends_on=None


def upgrade()->None:
	op.create_table(
		"diagnosis_runs",
		sa.Column("run_id",sa.Text(),nullable=False),
		sa.Column("request_id",sa.Text(),nullable=False),
		sa.Column("description",sa.Text(),nullable=False),
		sa.Column("status",sa.Text(),nullable=False),
		sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
		sa.Column("started_at",sa.DateTime(timezone=True),nullable=True),
		sa.Column("finished_at",sa.DateTime(timezone=True),nullable=True),
		sa.Column("error_code",sa.Text(),nullable=True),
		sa.PrimaryKeyConstraint("run_id",name="pk_diagnosis_runs"),
		sa.CheckConstraint(
			"status IN ('pending','running','succeeded','failed','cancelled')",
			name="ck_diagnosis_runs_status",
		),
	)


def downgrade()->None:
	op.drop_table("diagnosis_runs")
