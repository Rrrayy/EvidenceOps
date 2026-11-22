"""将发布指针改为文本ChunkSet，并允许关联可选向量集合。"""
from alembic import op
import sqlalchemy as sa


revision="0011"
down_revision="0010"
branch_labels=None
depends_on=None


def upgrade():
	connection=op.get_bind()
	op.add_column("knowledge_publications",sa.Column("chunk_set_id",sa.Text(),nullable=True))
	connection.execute(sa.text(
		"UPDATE knowledge_publications SET chunk_set_id=("
		"SELECT chunk_set_id FROM knowledge_embedding_sets "
		"WHERE knowledge_embedding_sets.embedding_set_id=knowledge_publications.embedding_set_id)"
	))
	if connection.scalar(sa.text("SELECT count(*) FROM knowledge_publications WHERE chunk_set_id IS NULL")):
		raise RuntimeError("存在无法关联ChunkSet的旧发布记录，拒绝迁移")
	if connection.dialect.name=="sqlite":
		with op.batch_alter_table("knowledge_publications") as batch:
			batch.alter_column("chunk_set_id",existing_type=sa.Text(),nullable=False)
			batch.alter_column("embedding_set_id",existing_type=sa.Text(),nullable=True)
			batch.create_foreign_key("fk_knowledge_publications_chunk_set_id","knowledge_chunk_sets",["chunk_set_id"],["chunk_set_id"])
	else:
		op.alter_column("knowledge_publications","chunk_set_id",existing_type=sa.Text(),nullable=False)
		op.alter_column("knowledge_publications","embedding_set_id",existing_type=sa.Text(),nullable=True)
		op.create_foreign_key("fk_knowledge_publications_chunk_set_id","knowledge_publications","knowledge_chunk_sets",["chunk_set_id"],["chunk_set_id"])


def downgrade():
	connection=op.get_bind()
	if connection.scalar(sa.text("SELECT count(*) FROM knowledge_publications WHERE embedding_set_id IS NULL")):
		raise RuntimeError("存在仅文本发布记录，不能降级为必须关联EmbeddingSet的结构")
	if connection.dialect.name=="sqlite":
		with op.batch_alter_table("knowledge_publications") as batch:
			batch.drop_constraint("fk_knowledge_publications_chunk_set_id",type_="foreignkey")
			batch.alter_column("embedding_set_id",existing_type=sa.Text(),nullable=False)
			batch.drop_column("chunk_set_id")
	else:
		op.drop_constraint("fk_knowledge_publications_chunk_set_id","knowledge_publications",type_="foreignkey")
		op.alter_column("knowledge_publications","embedding_set_id",existing_type=sa.Text(),nullable=False)
		op.drop_column("knowledge_publications","chunk_set_id")
