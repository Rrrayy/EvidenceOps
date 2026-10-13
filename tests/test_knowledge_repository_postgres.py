import os

import pytest

from evidenceops.application.document_ingestion import DocumentIngestionService
from evidenceops.domain.knowledge import KnowledgeDocument
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.connectors.local_document import LocalDocumentLoader


@pytest.mark.postgres
def test_knowledge_repository_persists_and_reloads(tmp_path):
	if not os.getenv("POSTGRES_PASSWORD"): pytest.skip("需要POSTGRES_PASSWORD")
	(root:=tmp_path/"knowledge").mkdir()
	(root/"rpc.md").write_text("# RPC\n\n检查线程池和重试。",encoding="utf-8")
	settings=DatabaseSettings.from_environment(); engine=create_database_engine(settings); factory=create_session_factory(engine)
	service=DocumentIngestionService(LocalDocumentLoader(root)); result=service.ingest(KnowledgeDocument("test-rpc","RPC","rpc.md"),"rpc.md")
	try:
		with factory.begin() as session: assert SqlAlchemyKnowledgeRepository(session).save_ingestion(result.document,result.version,result.chunk_set,result.chunks)
		with factory() as session: loaded=SqlAlchemyKnowledgeRepository(session).load_chunks("test-rpc",result.version.version_id)
		assert loaded==result.chunks
		with factory.begin() as session: assert SqlAlchemyKnowledgeRepository(session).save_ingestion(result.document,result.version,result.chunk_set,result.chunks) is True
	finally: engine.dispose()
