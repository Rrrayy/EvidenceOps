"""持久化编码集合、JSON向量和单文档默认发布指针；不使用pgvector。"""
from alembic import op
import sqlalchemy as sa

revision="0007"
down_revision="0006"
branch_labels=None
depends_on=None


def upgrade():
	op.create_table("knowledge_embedding_sets",sa.Column("embedding_set_id",sa.Text(),primary_key=True),
		sa.Column("chunk_set_id",sa.Text(),sa.ForeignKey("knowledge_chunk_sets.chunk_set_id"),nullable=False),
		sa.Column("config",sa.JSON(),nullable=False),sa.Column("config_fingerprint",sa.Text(),nullable=False),
		sa.Column("status",sa.Text(),nullable=False),sa.Column("error_code",sa.Text(),nullable=True),
		sa.CheckConstraint("status IN ('pending','building','ready','failed')",name="ck_embedding_sets_status"))
	op.create_table("knowledge_chunk_vectors",
		sa.Column("embedding_set_id",sa.Text(),sa.ForeignKey("knowledge_embedding_sets.embedding_set_id"),primary_key=True),
		sa.Column("chunk_id",sa.Text(),sa.ForeignKey("knowledge_chunks.chunk_id"),primary_key=True),sa.Column("vector",sa.JSON(),nullable=False))
	op.create_table("knowledge_publications",sa.Column("document_id",sa.Text(),sa.ForeignKey("knowledge_documents.document_id"),primary_key=True),
		sa.Column("embedding_set_id",sa.Text(),sa.ForeignKey("knowledge_embedding_sets.embedding_set_id"),nullable=False))


def downgrade():
	op.drop_table("knowledge_publications")
	op.drop_table("knowledge_chunk_vectors")
	op.drop_table("knowledge_embedding_sets")
