from dataclasses import replace
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import httpx
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker

from evidenceops.application.knowledge_splitter import KnowledgeSplitter
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.domain.knowledge import KnowledgeDocument,DocumentVersion,ChunkSet,SplitterConfig
from evidenceops.domain.knowledge_vectors import EncodingConfig,validate_vectors
from evidenceops.infrastructure.database.models import Base,KnowledgeEmbeddingSetRow
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.vector_repository import VectorRepository,PublicationConflict
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.providers.embedding_provider import HttpEmbeddingProvider


class TestEncoder:
	__test__=False
	def __init__(self,config,fail_at=None):
		self.config=config
		self.calls=0
		self.fail_at=fail_at
	def encode(self,texts,purpose,remaining):
		self.calls+=1
		if self.calls==self.fail_at: raise RuntimeError("batch failed")
		return tuple((1.0,0.0) if "RPC" in text else (0.0,1.0) for text in texts)


@pytest.fixture(params=["sqlite","postgres"])
def factory(request):
	if request.param=="postgres":
		if not os.getenv("POSTGRES_PASSWORD"): pytest.skip("需要POSTGRES_PASSWORD")
		engine=create_database_engine(DatabaseSettings.from_environment())
		factory=create_session_factory(engine)
	else:
		engine=create_engine("sqlite://")
		Base.metadata.create_all(engine)
		factory=sessionmaker(bind=engine,expire_on_commit=False)
	yield factory
	engine.dispose()


def setup_document(factory):
	document=KnowledgeDocument("vector-test-"+str(uuid4()),"排障参考","test:manual")
	version=DocumentVersion(document.document_id,document.source_ref,"RPC 超时应检查下游延迟。\n\n线程池饱和应检查活动线程和队列。")
	chunk_set=ChunkSet(version.version_id,SplitterConfig())
	chunks=KnowledgeSplitter().split(version,chunk_set)
	with factory.begin() as session:
		SqlAlchemyKnowledgeRepository(session).save_ingestion(document,version,chunk_set,chunks)
	return document,chunk_set,chunks


def test_build_publish_search_and_failed_rebuild(factory):
	document,chunk_set,chunks=setup_document(factory)
	config=EncodingConfig("test","test:local","test-v1",2)
	encoder=TestEncoder(config)
	service=VectorKnowledgeService(factory)
	set_id=service.build(document.document_id,chunk_set.chunk_set_id,config,encoder,batch_size=1)
	service.publish(document.document_id,set_id,None)
	result=service.search(document.document_id,"RPC",encoder,threshold=0.5)
	assert len(result)==1 and result[0].chunk==chunks[0]
	assert result[0].retrieval_method=="exact-cosine-v1"
	assert service.search(document.document_id,"RPC",encoder,chunk_ids=frozenset())==()
	assert service.search(document.document_id,"RPC",encoder,chunk_ids=frozenset([chunks[1].chunk_id]),threshold=0.5)==()
	with pytest.raises(PublicationConflict): service.publish(document.document_id,set_id,None)
	with pytest.raises(ValueError): service.search(document.document_id,"RPC",TestEncoder(replace(config,model="another-model")))
	with pytest.raises(RuntimeError): service.build(document.document_id,chunk_set.chunk_set_id,config,TestEncoder(config,2),batch_size=1)
	with factory() as session:
		assert VectorRepository(session).active(document.document_id)==set_id
		failed=session.scalars(select(KnowledgeEmbeddingSetRow).where(KnowledgeEmbeddingSetRow.chunk_set_id==chunk_set.chunk_set_id,KnowledgeEmbeddingSetRow.status=="failed")).all()
		assert len(failed)==1
	assert service.search(document.document_id,"RPC",encoder,threshold=0.5)==result


def test_embedding_http_reorders_and_rejects_duplicate_indices():
	config=EncodingConfig("test","https://embedding.example/v1/embeddings","test",2,document_mode="default",query_mode="default")
	def response(request):
		return httpx.Response(200,json={"data":[{"index":1,"embedding":[0,2]},{"index":0,"embedding":[3,0]}]})
	provider=HttpEmbeddingProvider(config,"test-key",transport=httpx.MockTransport(response))
	assert provider.encode(("first","second"),"document",10)==((1.0,0.0),(0.0,1.0))
	def duplicate(request):
		return httpx.Response(200,json={"data":[{"index":0,"embedding":[1,0]},{"index":0,"embedding":[0,1]}]})
	provider=HttpEmbeddingProvider(config,"test-key",transport=httpx.MockTransport(duplicate))
	with pytest.raises(ValueError): provider.encode(("first","second"),"document",10)


def test_candidate_budget_and_timeout(factory):
	document,chunk_set,chunks=setup_document(factory)
	config=EncodingConfig("test","test:local","test-v1",2)
	service=VectorKnowledgeService(factory)
	set_id=service.build(document.document_id,chunk_set.chunk_set_id,config,TestEncoder(config))
	service.publish(document.document_id,set_id,None)
	with pytest.raises(ValueError): VectorKnowledgeService(factory,max_candidates=1).search(document.document_id,"RPC",TestEncoder(config))
	with pytest.raises(ValueError): service.build(document.document_id,chunk_set.chunk_set_id,config,TestEncoder(config),budget=float("nan"))
	class TimeoutEncoder(TestEncoder):
		def encode(self,texts,purpose,remaining): raise TimeoutError("模拟供应商超时")
	with pytest.raises(TimeoutError): service.build(document.document_id,chunk_set.chunk_set_id,config,TimeoutEncoder(config))
	with factory() as session: assert VectorRepository(session).active(document.document_id)==set_id


def test_postgres_concurrent_first_publication(factory):
	with factory() as session:
		if session.bind.dialect.name!="postgresql": pytest.skip("真实行锁需要PostgreSQL")
	document,chunk_set,chunks=setup_document(factory)
	config=EncodingConfig("test","test:local","test-v1",2)
	service=VectorKnowledgeService(factory)
	sets=tuple(service.build(document.document_id,chunk_set.chunk_set_id,config,TestEncoder(config)) for _ in range(2))
	barrier=Barrier(2)
	def publish(set_id):
		barrier.wait(timeout=5)
		try:
			service.publish(document.document_id,set_id,None)
			return "published"
		except PublicationConflict: return "conflict"
	with ThreadPoolExecutor(max_workers=2) as pool:
		assert sorted(pool.map(publish,sets))==["conflict","published"]
	with factory() as session: assert VectorRepository(session).active(document.document_id) in sets


@pytest.mark.parametrize("vectors,count,dimensions",[([],1,2),([[1]],1,2),([[0,0]],1,2),([[float("nan"),1]],1,2)])
def test_batch_validation(vectors,count,dimensions):
	with pytest.raises(ValueError): validate_vectors(vectors,count,dimensions)
