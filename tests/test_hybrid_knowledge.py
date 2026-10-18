from dataclasses import replace
import math
import pytest

from evidenceops.application.hybrid_knowledge import fuse_rankings,keyword_ranking
from evidenceops.application.bm25_knowledge import BM25KnowledgeRetriever,bm25_ranking,tokenize
from evidenceops.application.knowledge_comparison import fragment_metrics,compare_cases
from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.application.knowledge_evidence import matches_to_evidence
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.domain.knowledge_vectors import EncodingConfig
from evidenceops.domain.knowledge import KnowledgeChunk,ChunkSet,SplitterConfig
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


def test_bm25_idf_length_normalization_and_metadata():
	items=corpus()
	result=BM25KnowledgeRetriever().search(items,"线程池 RPC",5)
	assert result and result[0].retrieval_method=='bm25-v1'
	assert result[0].retrieval_details['score_kind']=='bm25'
	assert result[0].retrieval_details['tokenizer']=='word-or-han-char-v1'
	assert tokenize('RPC RPC 超时')==('rpc','rpc','超','时')
	assert BM25KnowledgeRetriever().search(items,'zzzz_unseen_identifier',5)==()
	assert bm25_ranking(tuple(KnowledgeMatch(item,0,index+1) for index,item in enumerate(items)),"RPC",3)
	with pytest.raises(ValueError): BM25KnowledgeRetriever(k1=0)
	with pytest.raises(ValueError): BM25KnowledgeRetriever(b=2)


def scoring_chunks(*texts):
	chunk_set=ChunkSet('test-bm25-version',SplitterConfig(chunk_size=1000))
	return tuple(KnowledgeChunk(chunk_set,index,0,len(text),text) for index,text in enumerate(texts))


def test_bm25_numeric_oracle_idf_length_and_saturation():
	chunks=scoring_chunks('rare common common','common','other other other other')
	result=BM25KnowledgeRetriever().search(chunks,'rare common',3)
	by_id={match.chunk.chunk_id:match.score for match in result}
	average_length=8/3
	idf_rare=math.log(1+2.5/1.5)
	idf_common=math.log(1+1.5/2.5)
	denominator=1.2*(0.25+0.75*3/average_length)
	assert by_id[chunks[0].chunk_id]==pytest.approx(idf_rare*2.2/(1+denominator)+idf_common*4.4/(2+denominator))
	assert by_id[chunks[1].chunk_id]==pytest.approx(idf_common*2.2/(1+1.2*(0.25+0.75/average_length)))
	short,long=scoring_chunks('match','match filler filler filler')
	assert BM25KnowledgeRetriever().search((short,long),'match')[0].chunk==short
	frequencies=scoring_chunks('match','match match','match match match')
	scores={match.chunk.chunk_id:match.score for match in BM25KnowledgeRetriever(b=0).search(frequencies,'match')}
	first,second,third=(scores[chunk.chunk_id] for chunk in frequencies)
	assert first<second<third and third-second<second-first
	assert BM25KnowledgeRetriever().search(chunks,'rare rare common')==result


@pytest.mark.parametrize('kwargs',[{'k1':True},{'b':'0.75'},{'k1':float('nan')},{'b':float('inf')},{'k1':-1},{'b':-0.1}])
def test_bm25_rejects_invalid_parameters(kwargs):
	with pytest.raises(ValueError): BM25KnowledgeRetriever(**kwargs)


def test_bm25_empty_ties_token_boundaries_and_evidence_audit():
	chunks=scoring_chunks('rpc','rpc','rpc_timeout')
	retriever=BM25KnowledgeRetriever()
	result=retriever.search(chunks,'rpc')
	assert {match.chunk.chunk_id for match in result}=={chunk.chunk_id for chunk in chunks[:2]}
	assert [match.chunk.chunk_id for match in result]==sorted(chunk.chunk_id for chunk in chunks[:2])
	assert retriever.search((),'rpc')==()
	assert retriever.search(chunks,'!!!')==()
	assert retriever.search(scoring_chunks('!!!'),'rpc')==()
	with pytest.raises(ValueError): retriever.search((chunks[0],chunks[0]),'rpc')
	with pytest.raises(ValueError): retriever.search(chunks,' ')
	with pytest.raises(ValueError): retriever.search(chunks,'rpc',True)
	vector=tuple(KnowledgeMatch(chunk,0.5,index+1) for index,chunk in enumerate(chunks))
	lexical=bm25_ranking(vector,'rpc',10)
	fused=fuse_rankings(vector,lexical,3,keyword_name='bm25')
	assert fused[0].retrieval_details['bm25_config']==lexical[0].retrieval_details
	evidence=matches_to_evidence('run-bm25','call-bm25',fused)[0]
	assert evidence.source_metadata['retrieval_method']=='hybrid-rrf-bm25-v1'
	assert evidence.source_metadata['retrieval_details']['bm25_config']['k1']==1.2
	assert evidence.content_snapshot==fused[0].chunk.content


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
	before_bm25=encoder.calls
	assert service.search_many((document.document_id,),'RPC',encoder,top_k=1,method='bm25')
	assert encoder.calls==before_bm25
	assert service.search_many((document.document_id,),'RPC',encoder,top_k=1,method='hybrid_bm25',candidate_k=2)[0].retrieval_method=='hybrid-rrf-bm25-v1'
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
	assert report['results'][0]['required_chunk_ids']==case['required_chunk_ids']
	assert report['results'][0]['modes']['bm25']['required_ranks'][chunks[0].chunk_id]==1
	assert report['summary']['bm25']['negative_cases']==0
	assert set(report['summary'])=={'cosine','keyword','bm25','hybrid','hybrid_bm25'}
	assert all(value>=0 for value in report['results'][0]['timings'].values())
	# 单路词法不调用供应商；融合的供应商错误不能被伪装为空命中。
	failing=TestEncoder(config,fail_at=1)
	assert service.search_many((document.document_id,),'RPC',failing,method='bm25')
	assert failing.calls==0
	with pytest.raises(RuntimeError): service.search_many((document.document_id,),'RPC',failing,method='hybrid_bm25')
	assert service.search_many((document.document_id,),'RPC',encoder,method='bm25',chunk_ids=frozenset())==()
	assert service.search_many((document.document_id,),'zzzz_unseen_identifier',encoder,method='bm25')==()
	filtered_bm25=service.search_many((document.document_id,),'线程池',encoder,method='bm25',chunk_ids=frozenset((chunks[1].chunk_id,)))
	assert filtered_bm25 and filtered_bm25[0].chunk==chunks[1]
	with pytest.raises(ValueError): compare_cases(factory,(document.document_id,),encoder,[{**case,'relevant_chunk_ids':['missing']}])
	with pytest.raises(ValueError): compare_cases(factory,(document.document_id,),encoder,[{**case,'relevant_chunk_ids':[chunks[0].chunk_id]*2}])
	with pytest.raises(ValueError): compare_cases(factory,(document.document_id,),encoder,[{**case,'query':' '}])
	before=encoder.calls
	with pytest.raises(ValueError): compare_cases(factory,(document.document_id,),encoder,[case,{**case,'case_id':'invalid','query':' '}])
	assert encoder.calls==before
