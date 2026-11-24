"""将PostgreSQL知识向量迁移至pgvector，并记录向量维度。"""
import re

from alembic import op
import sqlalchemy as sa

from pgvector.sqlalchemy import Vector


revision="0012"
down_revision="0011"
branch_labels=None
depends_on=None


def _index_name(dimensions:int,fingerprint:str)->str:
	return f"ix_kcv_hnsw_{dimensions}_{fingerprint[:24]}"


def upgrade():
	connection=op.get_bind()
	dialect=connection.dialect.name
	if dialect not in ("postgresql","sqlite"): raise RuntimeError("pgvector迁移只支持PostgreSQL或SQLite")
	if dialect=="postgresql": op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
	op.add_column("knowledge_chunk_vectors",sa.Column("dimensions",sa.Integer(),nullable=True))
	op.add_column("knowledge_chunk_vectors",sa.Column("config_fingerprint",sa.Text(),nullable=True))
	op.add_column("knowledge_chunk_vectors",sa.Column("embedding",Vector().with_variant(sa.JSON(),"sqlite"),nullable=True))
	if dialect=="sqlite":
		connection.execute(sa.text(
			"UPDATE knowledge_chunk_vectors SET dimensions=json_array_length(vector),embedding=vector,config_fingerprint=("
			"SELECT config_fingerprint FROM knowledge_embedding_sets "
			"WHERE knowledge_embedding_sets.embedding_set_id=knowledge_chunk_vectors.embedding_set_id)"
		))
		if connection.scalar(sa.text("SELECT count(*) FROM knowledge_chunk_vectors WHERE dimensions IS NULL OR dimensions<1 OR config_fingerprint IS NULL OR embedding IS NULL")):
			raise RuntimeError("旧JSON向量缺少有效维度、配置指纹或回填值，拒绝迁移")
		with op.batch_alter_table("knowledge_chunk_vectors") as batch:
			batch.alter_column("dimensions",existing_type=sa.Integer(),nullable=False)
			batch.alter_column("config_fingerprint",existing_type=sa.Text(),nullable=False)
			batch.alter_column("embedding",existing_type=sa.JSON(),nullable=False)
		return
	connection.execute(sa.text(
		"UPDATE knowledge_chunk_vectors SET dimensions=jsonb_array_length(vector),"
		"embedding=vector::text::vector,config_fingerprint=("
		"SELECT config_fingerprint FROM knowledge_embedding_sets "
		"WHERE knowledge_embedding_sets.embedding_set_id=knowledge_chunk_vectors.embedding_set_id)"
	))
	if connection.scalar(sa.text("SELECT count(*) FROM knowledge_chunk_vectors WHERE dimensions IS NULL OR dimensions<1 OR dimensions>16000 OR config_fingerprint IS NULL OR embedding IS NULL")):
		raise RuntimeError("旧JSON向量维度无效或pgvector回填缺少值，拒绝迁移")
	op.alter_column("knowledge_chunk_vectors","dimensions",existing_type=sa.Integer(),nullable=False)
	op.alter_column("knowledge_chunk_vectors","config_fingerprint",existing_type=sa.Text(),nullable=False)
	op.alter_column("knowledge_chunk_vectors","embedding",existing_type=Vector(),nullable=False)
	profiles=connection.execute(sa.text(
		"SELECT DISTINCT dimensions,config_fingerprint FROM knowledge_chunk_vectors WHERE dimensions<=2000 "
		"ORDER BY dimensions,config_fingerprint"
	)).all()
	for dimension,fingerprint in profiles:
		if not re.fullmatch(r"[0-9a-f]{64}",fingerprint):
			raise RuntimeError("EmbeddingSet配置指纹无效，拒绝创建HNSW索引")
		name=_index_name(int(dimension),fingerprint)
		op.execute(sa.text(
			f"CREATE INDEX {name} ON knowledge_chunk_vectors USING hnsw ((embedding::vector({int(dimension)})) vector_cosine_ops) "
			f"WITH (m=16,ef_construction=64) WHERE dimensions={int(dimension)} AND config_fingerprint='{fingerprint}'"
		))


def downgrade():
	connection=op.get_bind()
	if connection.dialect.name=="postgresql":
		indexes=connection.execute(sa.text(
			"SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() AND tablename='knowledge_chunk_vectors' "
			"AND indexname LIKE 'ix_kcv_hnsw_%'"
		)).scalars().all()
		for name in indexes: op.execute(f"DROP INDEX IF EXISTS {name}")
	if connection.dialect.name=="sqlite":
		with op.batch_alter_table("knowledge_chunk_vectors") as batch:
			batch.drop_column("embedding")
			batch.drop_column("config_fingerprint")
			batch.drop_column("dimensions")
	else:
		op.drop_column("knowledge_chunk_vectors","embedding")
		op.drop_column("knowledge_chunk_vectors","config_fingerprint")
		op.drop_column("knowledge_chunk_vectors","dimensions")
