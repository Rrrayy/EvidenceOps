import os

import pytest

from evidenceops.application.document_ingestion import DocumentIngestionService
from evidenceops.domain.knowledge import KnowledgeDocument,SplitterConfig
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
		second=service.ingest(KnowledgeDocument("test-rpc","RPC","rpc.md"),"rpc.md",SplitterConfig(chunk_size=5,chunk_overlap=1))
		with factory.begin() as session: assert SqlAlchemyKnowledgeRepository(session).save_ingestion(second.document,second.version,second.chunk_set,second.chunks)
		with factory() as session:
			repository=SqlAlchemyKnowledgeRepository(session)
			loaded=repository.load_chunks("test-rpc",result.chunk_set.chunk_set_id)
			second_loaded=repository.load_chunks("test-rpc",second.chunk_set.chunk_set_id)
		assert loaded==result.chunks
		assert second_loaded==second.chunks
		assert second.chunk_set.chunk_set_id!=result.chunk_set.chunk_set_id
		with factory() as session:
			with pytest.raises(ValueError): SqlAlchemyKnowledgeRepository(session).load_chunks("test-rpc",None)
		with factory.begin() as session: assert SqlAlchemyKnowledgeRepository(session).save_ingestion(result.document,result.version,result.chunk_set,result.chunks) is True
	finally: engine.dispose()
