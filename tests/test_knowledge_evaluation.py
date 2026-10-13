from evidenceops.application.knowledge_evaluation import RetrievalCase,evaluate_case
from evidenceops.application.knowledge_retrieval import KeywordKnowledgeRetriever
from evidenceops.application.knowledge_splitter import KnowledgeSplitter
from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,SplitterConfig


def corpus():
	version=DocumentVersion("rpc","knowledge/rpc.md","# RPC超时\n\n检查线程池 active_threads 和 pending_tasks。\n\n## 重试\n\nmax_retries 只是允许重试，不代表已经发生。")
	return KnowledgeSplitter().split(version,ChunkSet(version.version_id,SplitterConfig(chunk_size=100,chunk_overlap=10)))


def test_retrieval_metrics_are_calculated_from_ranked_matches()->None:
	matches=KeywordKnowledgeRetriever().search(corpus(),"线程池 pending_tasks",5)
	case=RetrievalCase("线程池",frozenset({matches[0].chunk.chunk_id}))
	metrics=evaluate_case(case,matches)
	assert metrics["recall_at_k"]==1.0
	assert metrics["mrr"]==1.0
	assert 0<metrics["precision_at_k"]<=1
