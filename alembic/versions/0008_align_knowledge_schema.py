"""补偿历史库快照列缺失，统一PostgreSQL JSONB存储；不删除已有数据。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision="0008"
down_revision="0007"
branch_labels=None
depends_on=None


def upgrade():
	connection=op.get_bind()
	columns={column["name"] for column in sa.inspect(connection).get_columns("evidences")}
	if "content_snapshot" not in columns: op.add_column("evidences",sa.Column("content_snapshot",sa.Text(),nullable=True))
	if "source_metadata" not in columns: op.add_column("evidences",sa.Column("source_metadata",sa.JSON(),nullable=True))
	if connection.dialect.name=="postgresql":
		for table,column in (("evidences","source_metadata"),("knowledge_chunks","heading_path"),("knowledge_embedding_sets","config"),("knowledge_chunk_vectors","vector")):
			op.alter_column(table,column,type_=JSONB(),postgresql_using=column+"::jsonb")


def downgrade():
	# 补齐的快照列属于0006契约，不在本补偿迁移降级时删除用户数据。
	if op.get_bind().dialect.name=="postgresql":
		for table,column in (("evidences","source_metadata"),("knowledge_chunks","heading_path"),("knowledge_embedding_sets","config"),("knowledge_chunk_vectors","vector")):
			op.alter_column(table,column,type_=sa.JSON(),postgresql_using=column+"::json")
