"""为诊断运行表增加模型配置快照；旧运行保留空值，不推断历史配置。"""
from alembic import op
import sqlalchemy as sa
revision="0005"
down_revision="0004"
branch_labels=None
depends_on=None

def upgrade():
	op.add_column("diagnosis_runs",sa.Column("model_config",sa.JSON(),nullable=True))

def downgrade():
	with op.batch_alter_table("diagnosis_runs") as table: table.drop_column("model_config")
