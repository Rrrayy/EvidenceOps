"""固定语料词法对照，不调用供应商；不能代替真实向量融合或生成验收。"""
import json
from pathlib import Path
from time import perf_counter

from evidenceops.application.bm25_knowledge import BM25KnowledgeRetriever
from evidenceops.application.document_ingestion import DocumentIngestionService
from evidenceops.application.knowledge_comparison import fragment_metrics
from evidenceops.application.knowledge_corpus_cli import read_manifest
from evidenceops.application.knowledge_retrieval import KeywordKnowledgeRetriever
from evidenceops.connectors.local_document import LocalDocumentLoader
from evidenceops.domain.knowledge import KnowledgeDocument


def test_frozen_corpus_lexical_comparison():
	root=Path(__file__).resolve().parents[1]/'samples'/'knowledge'
	manifest=read_manifest(root/'manifest.json')
	ingestion=DocumentIngestionService(LocalDocumentLoader(root))
	chunks=tuple(chunk for item in manifest['documents'] for chunk in ingestion.ingest(
		KnowledgeDocument(item['document_id'],item['title'],item['path']),item['path']).chunks)
	assert len(chunks)==37
	identities={chunk.chunk_id for chunk in chunks}
	seen_queries=set()
	for filename,expected_count in (('fragment_cases.json',17),('fragment_acceptance_cases.json',8)):
		cases=json.loads((root/filename).read_text(encoding='utf-8-sig'))['cases']
		assert len(cases)==expected_count
		assert len({case['case_id'] for case in cases})==len(cases)
		assert not seen_queries&{case['query'] for case in cases}
		seen_queries.update(case['query'] for case in cases)
		for case in cases:
			assert set(case['required_chunk_ids'])<=set(case['relevant_chunk_ids'])<=identities
		for name,retriever in (('keyword',KeywordKnowledgeRetriever()),('bm25',BM25KnowledgeRetriever())):
			started=perf_counter()
			positive=[]
			negative=[]
			failed=[]
			for case in cases:
				matches=retriever.search(chunks,case['query'],3)
				metric=fragment_metrics(tuple(match.chunk.chunk_id for match in matches),
					frozenset(case['relevant_chunk_ids']),frozenset(case['required_chunk_ids']),3)
				if case['relevant_chunk_ids']:
					positive.append(metric)
					if not metric['required_hit']: failed.append(case['case_id'])
				else: negative.append({'case_id':case['case_id'],'returned_count':len(matches)})
			# 输出可复核的观测，不以某个漂亮分数作为算法正确性的证明。
			print(json.dumps({'cases':filename,'method':name,'positive_cases':len(positive),
				'metrics':{key:sum(value[key] for value in positive)/len(positive)
					for key in ('precision_at_k','recall_at_k','reciprocal_rank')},
				'required_passes':sum(value['required_hit'] for value in positive),'failed_required':failed,
				'negative':negative,'local_seconds':perf_counter()-started},ensure_ascii=False))
