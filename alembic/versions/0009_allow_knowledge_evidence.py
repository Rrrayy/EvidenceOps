"""让迁移创建的数据库允许knowledge证据，与ORM约束保持一致。"""
from alembic import op
import sqlalchemy as sa

revision="0009"
down_revision="0008"
branch_labels=None
depends_on=None


def upgrade():
	with op.batch_alter_table("evidences") as batch:
		batch.drop_constraint("ck_evidences_source",type_="check")
		batch.create_check_constraint("ck_evidences_source","source IN ('log','metric','config','knowledge')")


def downgrade():
	# 不静默删除已归档知识事实；存在knowledge时拒绝降级。
	if op.get_bind().scalar(sa.text("SELECT count(*) FROM evidences WHERE source='knowledge'")):
		raise RuntimeError("存在knowledge证据，不能降级来源约束")
	with op.batch_alter_table("evidences") as batch:
		batch.drop_constraint("ck_evidences_source",type_="check")
		batch.create_check_constraint("ck_evidences_source","source IN ('log','metric','config')")
