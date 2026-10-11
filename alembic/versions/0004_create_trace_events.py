from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision="0004"
down_revision="0003"
branch_labels=None
depends_on=None


def upgrade()->None:
	op.create_table("trace_events",
		sa.Column("event_id",sa.Text(),nullable=False),
		sa.Column("run_id",sa.Text(),nullable=False),
		sa.Column("sequence",sa.BigInteger(),nullable=False),
		sa.Column("event_type",sa.Text(),nullable=False),
		sa.Column("payload",sa.JSON().with_variant(JSONB(),"postgresql"),nullable=False),
		sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False),
		sa.PrimaryKeyConstraint("event_id",name="pk_trace_events"),
		sa.ForeignKeyConstraint(["run_id"],["diagnosis_runs.run_id"],name="fk_trace_events_run_id"),
		sa.UniqueConstraint("run_id","sequence",name="uq_trace_events_run_sequence"),
		sa.CheckConstraint("sequence>0",name="ck_trace_events_sequence"))


def downgrade()->None:
	op.drop_table("trace_events")
