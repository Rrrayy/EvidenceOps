from dataclasses import replace
import pytest

from evidenceops.application.hybrid_knowledge import fuse_rankings,keyword_ranking
from evidenceops.application.knowledge_comparison import fragment_metrics,compare_cases
from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.application.knowledge_evidence import matches_to_evidence
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.domain.knowledge_vectors import EncodingConfig
from test_knowledge_evidence import corpus
from test_vector_knowledge import factory,setup_document,TestEncoder


def test_rrf_uses_ranks_deduplicates_and_preserves_audit():
	first,second=tuple(KnowledgeMatch(chunk,1000-index,index+1) for index,chunk in enumerate(corpus()))[:2]
	result=fuse_rankings((first,second),(replace(second,score=0.1),),2)
	assert result[0].chunk==second.chunk
	assert result[0].score==pytest.approx(1/62+1/61)
	assert result[0].retrieval_details['branches']=={'vector':{'rank':2,'score':999},'keyword':{'rank':1,'score':0.1}}
	assert len(result)==2
	evidence=matches_to_evidence('run-hybrid','call-test',result)[0]
	assert evidence.source_metadata['retrieval_details']==result[0].retrieval_details
	assert evidence.content_snapshot==second.chunk.content
	assert fuse_rankings((),(),3)==()
	assert fuse_rankings((first,),(),3)[0].score==pytest.approx(1/61)
	with pytest.raises(ValueError): fuse_rankings((first,first),(),3)
	with pytest.raises(ValueError): fuse_rankings((first,),(replace(first,config_fingerprint='different'),),3)


def test_stable_tie_and_keyword_empty():
	first,second=tuple(KnowledgeMatch(chunk,1,index+1) for index,chunk in enumerate(corpus()))[:2]
	result=fuse_rankings((first,second),(second,first),2)
	assert [item.chunk.chunk_id for item in result]==sorted([first.chunk.chunk_id,second.chunk.chunk_id])
	assert keyword_ranking((first,second),'unmatched-word',10)==()
	with pytest.raises(ValueError): keyword_ranking((first,first),'RPC',10)


def test_metric_denominators_and_negative_semantics():
	result=fragment_metrics(('a',),frozenset(('a','b')),frozenset(('b',)),3)
	assert result['precision_at_k']==1/3 and result['recall_at_k']==0.5
	assert result['reciprocal_rank']==1 and result['required_hit'] is False
	assert fragment_metrics(('x',),frozenset(),frozenset(),3)['recall_at_k'] is None
	with pytest.raises(ValueError): fragment_metrics(('a','a'),frozenset(('a',)),frozenset(),3)
	with pytest.raises(ValueError): fragment_metrics((),frozenset(),frozenset(('a',)),3)


def test_shared_published_snapshot_filter_and_comparison(factory):
	document,chunk_set,chunks=setup_document(factory)
	config=EncodingConfig('test','test:local','test-v1',2)
	encoder=TestEncoder(config)
	service=VectorKnowledgeService(factory)
	identity=service.build(document.document_id,chunk_set.chunk_set_id,config,encoder)
	service.publish(document.document_id,identity,None)
	before=encoder.calls
	result=service.search_many((document.document_id,),'RPC',encoder,top_k=1,method='hybrid',candidate_k=2)
	assert len(result)==1 and encoder.calls==before+1
	assert result[0].retrieval_method=='hybrid-rrf-keyword-v1'
	assert service.search_many((document.document_id,),'RPC',encoder,method='hybrid',chunk_ids=frozenset())==()
	filtered=service.search_many((document.document_id,),'RPC',encoder,method='hybrid',top_k=1,chunk_ids=frozenset((chunks[1].chunk_id,)))
	assert filtered[0].chunk==chunks[1]
	for kwargs in ({'threshold':0.3},{'top_k':'3'},{'top_k':3,'candidate_k':2}):
		with pytest.raises(ValueError): service.search_many((document.document_id,),'RPC',encoder,method='hybrid',**kwargs)
	with pytest.raises(ValueError): VectorKnowledgeService(factory,max_candidates=1).search_many((document.document_id,),'RPC',encoder,method='hybrid')
	case={'case_id':'test','query':'RPC','relevant_chunk_ids':[chunks[0].chunk_id],'required_chunk_ids':[chunks[0].chunk_id]}
	before=encoder.calls
	report=compare_cases(factory,(document.document_id,),encoder,[case])
	assert encoder.calls==before+1 and report['positive_cases']==1
	assert report['summary']['hybrid']['required_passes']==1
	assert report['snapshot']
	with pytest.raises(ValueError): compare_cases(factory,(document.document_id,),encoder,[{**case,'relevant_chunk_ids':['missing']}])
	with pytest.raises(ValueError): compare_cases(factory,(document.document_id,),encoder,[{**case,'relevant_chunk_ids':[chunks[0].chunk_id]*2}])
	with pytest.raises(ValueError): compare_cases(factory,(document.document_id,),encoder,[{**case,'query':' '}])
