from evidenceops.application.knowledge_evidence import matches_to_evidence
from evidenceops.application.knowledge_retrieval import KeywordKnowledgeRetriever
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.application.knowledge_splitter import KnowledgeSplitter
from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,SplitterConfig


def corpus():
	version=DocumentVersion("rpc","knowledge/rpc.md","# RPC超时\n\n检查线程池 active_threads 和 pending_tasks。\n\n## 重试\n\nmax_retries 只是允许重试，不代表已经发生。")
	return KnowledgeSplitter().split(version,ChunkSet(version.version_id,SplitterConfig(chunk_size=100,chunk_overlap=10)))


def test_one_search_call_creates_one_evidence_per_match()->None:
	run=DiagnosisRun("run-knowledge","request-knowledge","查询知识")
	matches=KeywordKnowledgeRetriever().search(corpus(),"线程池 重试",5)
	evidences=matches_to_evidence(run,"call-1",matches)
	assert len(evidences)==len(matches)
	assert all(evidence.source.value=="knowledge" for evidence in evidences)
	assert len({evidence.evidence_id for evidence in evidences})==len(evidences)
	assert all(evidence.run_id==run.run_id for evidence in evidences)
