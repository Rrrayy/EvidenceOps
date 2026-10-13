from pathlib import Path

import pytest

from evidenceops.application.document_ingestion import DocumentIngestionService
from evidenceops.application.knowledge_splitter import KnowledgeSplitter
from evidenceops.connectors.local_document import LocalDocumentLoader
from evidenceops.domain.knowledge import KnowledgeDocument,SplitterConfig


def make_service(tmp_path)->DocumentIngestionService:
	(tmp_path/"rpc.md").write_text("# RPC排障\n\n检查线程池和调用链。\n\n配置允许重试不代表发生重试。",encoding="utf-8")
	return DocumentIngestionService(LocalDocumentLoader(tmp_path),KnowledgeSplitter())


def test_ingestion_composes_loader_version_and_splitter(tmp_path)->None:
	service=make_service(tmp_path)
	result=service.ingest(KnowledgeDocument("rpc-runbook","RPC排障手册","knowledge/rpc.md"),"rpc.md")
	assert result.is_new_version is True
	assert result.version.document_id=="rpc-runbook"
	assert result.chunk_set.version_id==result.version.version_id
	assert result.chunks
	assert all(chunk.chunk_set.chunk_set_id==result.chunk_set.chunk_set_id for chunk in result.chunks)


def test_same_version_and_splitter_are_idempotent_in_memory(tmp_path)->None:
	service=make_service(tmp_path)
	document=KnowledgeDocument("rpc-runbook","RPC排障手册","knowledge/rpc.md")
	first=service.ingest(document,"rpc.md")
	second=service.ingest(document,"rpc.md")
	assert second.is_new_version is False
	assert second.version.version_id==first.version.version_id
	assert second.chunk_set.chunk_set_id==first.chunk_set.chunk_set_id
	assert second.chunks==first.chunks
	assert service.get_cached(first.version.version_id,first.chunk_set.chunk_set_id)==first


def test_changed_content_creates_new_version(tmp_path)->None:
	service=make_service(tmp_path)
	document=KnowledgeDocument("rpc-runbook","RPC排障手册","knowledge/rpc.md")
	first=service.ingest(document,"rpc.md")
	(tmp_path/"rpc.md").write_text("# RPC排障\n\n新的检查步骤。",encoding="utf-8")
	second=service.ingest(document,"rpc.md")
	assert second.is_new_version is True
	assert second.version.version_id!=first.version.version_id
	assert service.get_cached(first.version.version_id,first.chunk_set.chunk_set_id)==first


def test_changed_splitter_config_reuses_version_but_creates_new_chunk_set(tmp_path)->None:
	service=make_service(tmp_path)
	document=KnowledgeDocument("rpc-runbook","RPC排障手册","knowledge/rpc.md")
	first=service.ingest(document,"rpc.md",SplitterConfig(chunk_size=20,chunk_overlap=3))
	second=service.ingest(document,"rpc.md",SplitterConfig(chunk_size=30,chunk_overlap=3))
	assert second.is_new_version is True
	assert second.version.version_id==first.version.version_id
	assert second.chunk_set.chunk_set_id!=first.chunk_set.chunk_set_id


def test_failure_does_not_leave_partial_cache_entry(tmp_path)->None:
	service=make_service(tmp_path)
	document=KnowledgeDocument("rpc-runbook","RPC排障手册","knowledge/rpc.md")
	(tmp_path/"rpc.md").write_bytes(b"\xff")
	with pytest.raises(Exception):
		service.ingest(document,"rpc.md")
	assert service.get_cached("version-missing","chunks-missing") is None


@pytest.mark.parametrize("document,relative_path",[(None,"rpc.md"),("bad","rpc.md"),(KnowledgeDocument("d","t","s"),"")])
def test_ingestion_rejects_invalid_inputs(tmp_path,document,relative_path)->None:
	service=make_service(tmp_path)
	with pytest.raises((TypeError,ValueError)):
		service.ingest(document,relative_path)
