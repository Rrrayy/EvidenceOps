import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from evidenceops.application.document_ingestion import DocumentIngestionService
from evidenceops.connectors.local_document import LocalDocumentLoader
from evidenceops.domain.knowledge import KnowledgeDocument,SplitterConfig
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.models import Base


def test_repository_persists_multiple_chunk_sets_for_one_version(tmp_path)->None:
	knowledge_root=tmp_path/"knowledge"
	knowledge_root.mkdir()
	(knowledge_root/"rpc.md").write_text("# RPC\n\n检查线程池和重试。",encoding="utf-8")
	engine=create_engine("sqlite://")
	Base.metadata.create_all(engine)
	session_factory=sessionmaker(bind=engine,expire_on_commit=False)
	document=KnowledgeDocument("test-rpc-multiple-sets","RPC","rpc.md")
	service=DocumentIngestionService(LocalDocumentLoader(knowledge_root))
	first=service.ingest(document,"rpc.md")
	second=service.ingest(document,"rpc.md",SplitterConfig(chunk_size=5,chunk_overlap=1))
	try:
		with session_factory.begin() as session:
			repository=SqlAlchemyKnowledgeRepository(session)
			assert repository.save_ingestion(first.document,first.version,first.chunk_set,first.chunks)
		with session_factory.begin() as session:
			repository=SqlAlchemyKnowledgeRepository(session)
			assert repository.save_ingestion(second.document,second.version,second.chunk_set,second.chunks)
		with session_factory() as session:
			repository=SqlAlchemyKnowledgeRepository(session)
			first_loaded=repository.load_chunks(document.document_id,first.chunk_set.chunk_set_id)
			second_loaded=repository.load_chunks(document.document_id,second.chunk_set.chunk_set_id)
			wrong_document=repository.load_chunks("another-document",second.chunk_set.chunk_set_id)
		assert first_loaded==first.chunks
		assert second_loaded==second.chunks
		assert first.chunk_set.chunk_set_id!=second.chunk_set.chunk_set_id
		assert wrong_document==()
		with session_factory() as session:
			with pytest.raises(ValueError):
				SqlAlchemyKnowledgeRepository(session).load_chunks(document.document_id,"")
		with session_factory.begin() as session:
			assert SqlAlchemyKnowledgeRepository(session).save_ingestion(first.document,first.version,first.chunk_set,first.chunks)
	finally:
		engine.dispose()
