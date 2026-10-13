from evidenceops.application.knowledge_retrieval import KeywordKnowledgeRetriever
from evidenceops.application.knowledge_splitter import KnowledgeSplitter
from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,SplitterConfig


def corpus():
	version=DocumentVersion("rpc","knowledge/rpc.md","# RPC超时\n\n检查线程池 active_threads 和 pending_tasks。\n\n## 重试\n\nmax_retries 只是允许重试，不代表已经发生。")
	return KnowledgeSplitter().split(version,ChunkSet(version.version_id,SplitterConfig(chunk_size=100,chunk_overlap=10)))


def test_keyword_retrieval_is_deterministic_and_ranked()->None:
	first=KeywordKnowledgeRetriever().search(corpus(),"线程池 pending_tasks")
	second=KeywordKnowledgeRetriever().search(corpus(),"线程池 pending_tasks")
	assert first==second
	assert first[0].rank==1
	assert "线程池" in first[0].chunk.content


def test_no_match_is_successful_empty_result()->None:
	assert KeywordKnowledgeRetriever().search(corpus(),"数据库分片") == ()


def test_top_k_and_empty_query_are_validated()->None:
	import pytest
	with pytest.raises(ValueError): KeywordKnowledgeRetriever().search(corpus(),"",1)
	with pytest.raises(ValueError): KeywordKnowledgeRetriever().search(corpus(),"线程池",0)
