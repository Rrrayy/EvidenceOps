"""统一读取受支持的迁移链；备份结构兼容需要显式登记，不能猜测未来版本。"""
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect,text


class UnsupportedSchema(ValueError):
	pass


def migration_config():
	root=Path(__file__).resolve().parents[3]
	config=Config(str(root/"alembic.ini"))
	config.set_main_option("script_location",str(root/"alembic"))
	return config


@lru_cache(maxsize=1)
def migration_chain()->tuple[str,...]:
	script=ScriptDirectory.from_config(migration_config())
	if len(script.get_heads())!=1: raise UnsupportedSchema("迁移存在多个分支头，需先完成版本合并")
	return tuple(revision.revision for revision in reversed(tuple(script.walk_revisions())))


def current_schema()->str:
	return migration_chain()[-1]


def require_supported(version:str|None)->None:
	if version is not None and version not in migration_chain():
		raise UnsupportedSchema("数据库版本不受当前程序支持，不能自动降级")


def database_schema(connection)->str|None:
	if not inspect(connection).has_table("alembic_version"): return None
	versions=connection.scalars(text("SELECT version_num FROM alembic_version")).all()
	if len(versions)>1: raise UnsupportedSchema("数据库存在多个迁移头，拒绝自动操作")
	version=versions[0] if versions else None
	require_supported(version)
	return version


def archive_shape(version:str)->dict[str,set[str]]:
	from evidenceops.infrastructure.database.models import Base
	# 迁移链决定可升级性；档案兼容则逐版本明确哪些表和字段当时存在。
	revisions=("0001","0002","0003","0004","0005","0006","0007","0008","0009","0010")
	if version not in revisions: raise UnsupportedSchema("备份版本不受支持")
	index=revisions.index(version)
	introduced={"diagnosis_runs":"0001","evidences":"0002","diagnosis_reports":"0003",
		"execution_records":"0003","trace_events":"0004","knowledge_documents":"0006",
		"knowledge_versions":"0006","knowledge_chunk_sets":"0006","knowledge_chunks":"0006",
		"knowledge_embedding_sets":"0007","knowledge_chunk_vectors":"0007","knowledge_publications":"0007"}
	introduced["model_context_audits"]="0010"
	shape={table.name:{column.name for column in table.columns} for table in Base.metadata.sorted_tables
		if table.name in introduced and revisions.index(introduced[table.name])<=index}
	for column in ("token_summary",):
		if "diagnosis_runs" in shape and index<revisions.index("0010"): shape["diagnosis_runs"].discard(column)
	for column in ("estimated_input_tokens","reserved_output_tokens","reported_input_tokens","reported_output_tokens","reported_total_tokens","usage_status","payload_hash"):
		if "execution_records" in shape and index<revisions.index("0010"): shape["execution_records"].discard(column)
	if index<revisions.index("0005"): shape["diagnosis_runs"].discard("model_config")
	if "evidences" in shape and index<revisions.index("0006"):
		shape["evidences"]-={"content_snapshot","source_metadata"}
	return shape
