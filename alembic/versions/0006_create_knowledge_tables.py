"""建立知识文档版本、切分集合和片段表，保存不可变导入结果。"""
from alembic import op
import sqlalchemy as sa

revision="0006"
down_revision="0005"
branch_labels=None
depends_on=None

def upgrade():
	op.add_column("evidences",sa.Column("content_snapshot",sa.Text(),nullable=True))
	op.add_column("evidences",sa.Column("source_metadata",sa.JSON(),nullable=True))
	op.create_table("knowledge_documents",sa.Column("document_id",sa.Text(),primary_key=True),sa.Column("title",sa.Text(),nullable=False),sa.Column("source_ref",sa.Text(),nullable=False))
	op.create_table("knowledge_versions",sa.Column("version_id",sa.Text(),primary_key=True),sa.Column("document_id",sa.Text(),sa.ForeignKey("knowledge_documents.document_id"),nullable=False),sa.Column("source_ref",sa.Text(),nullable=False),sa.Column("content",sa.Text(),nullable=False),sa.Column("content_hash",sa.Text(),nullable=False),sa.Column("status",sa.Text(),nullable=False),sa.UniqueConstraint("document_id","version_id",name="uq_knowledge_versions_document_version"))
	op.create_table("knowledge_chunk_sets",sa.Column("chunk_set_id",sa.Text(),primary_key=True),sa.Column("version_id",sa.Text(),sa.ForeignKey("knowledge_versions.version_id"),nullable=False),sa.Column("algorithm_version",sa.Text(),nullable=False),sa.Column("chunk_size",sa.Integer(),nullable=False),sa.Column("chunk_overlap",sa.Integer(),nullable=False))
	op.create_table("knowledge_chunks",sa.Column("chunk_id",sa.Text(),primary_key=True),sa.Column("chunk_set_id",sa.Text(),sa.ForeignKey("knowledge_chunk_sets.chunk_set_id"),nullable=False),sa.Column("chunk_index",sa.Integer(),nullable=False),sa.Column("start_offset",sa.Integer(),nullable=False),sa.Column("end_offset",sa.Integer(),nullable=False),sa.Column("content",sa.Text(),nullable=False),sa.Column("content_hash",sa.Text(),nullable=False),sa.Column("heading_path",sa.JSON(),nullable=False),sa.UniqueConstraint("chunk_set_id","chunk_index",name="uq_knowledge_chunks_set_index"))

def downgrade():
	op.drop_column("evidences","source_metadata")
	op.drop_column("evidences","content_snapshot")
	op.drop_table("knowledge_chunks")
	op.drop_table("knowledge_chunk_sets")
	op.drop_table("knowledge_versions")
	op.drop_table("knowledge_documents")
