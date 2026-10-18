"""融合同一候选快照的排名；不混加词频与cosine分数。"""
from dataclasses import replace

from evidenceops.application.knowledge_retrieval import KnowledgeMatch,KeywordKnowledgeRetriever


def fuse_rankings(vector:tuple[KnowledgeMatch,...],keyword:tuple[KnowledgeMatch,...],top_k:int,rrf_constant:int=60,keyword_name:str="keyword")->tuple[KnowledgeMatch,...]:
	if type(top_k) is not int or not 1<=top_k<=50: raise ValueError("top_k必须在1到50之间")
	if type(rrf_constant) is not int or not 1<=rrf_constant<=1000: raise ValueError("RRF常数必须在1到1000之间")
	scores={}
	objects={}
	details={}
	if keyword_name not in ("keyword","bm25"): raise ValueError("关键词分支名称无效")
	lexical_config=keyword[0].retrieval_details if keyword_name=="bm25" and keyword else None
	for name,matches in (("vector",vector),(keyword_name,keyword)):
		seen=set()
		for rank,match in enumerate(matches,1):
			identity=match.chunk.chunk_id
			if identity in seen: raise ValueError("单路排名不能包含重复片段")
			seen.add(identity)
			if identity in objects and any(getattr(objects[identity],field)!=getattr(match,field)
				for field in ("chunk","embedding_set_id","config_fingerprint","document_id","source_ref")):
				raise ValueError("两路检索不是同一片段快照")
			objects[identity]=match
			scores[identity]=scores.get(identity,0.0)+1/(rrf_constant+rank)
			details.setdefault(identity,{})[name]={"rank":rank,"score":match.score}
	# 不依赖输入集合遍历顺序；分数相同时以稳定身份决定次序。
	identities=sorted(scores,key=lambda identity:(-scores[identity],identity))[:top_k]
	return tuple(replace(objects[identity],score=scores[identity],rank=rank,retrieval_method="hybrid-rrf-"+keyword_name+"-v1",
		retrieval_details={"score_kind":"rrf","rrf_constant":rrf_constant,"branches":details[identity],
			"vector_candidates":len(vector),keyword_name+"_candidates":len(keyword),
			**({"bm25_config":lexical_config} if lexical_config is not None else {})}) for rank,identity in enumerate(identities,1))


def keyword_ranking(matches:tuple[KnowledgeMatch,...],query:str,candidate_k:int)->tuple[KnowledgeMatch,...]:
	if type(candidate_k) is not int or not 1<=candidate_k<=50: raise ValueError("每路候选必须在1到50之间")
	if len({match.chunk.chunk_id for match in matches})!=len(matches): raise ValueError("候选片段不能重复")
	# 复用原词频算法，不把它称为BM25；身份用于稳定处理跨文档同分。
	by_id={match.chunk.chunk_id:match for match in matches}
	found=KeywordKnowledgeRetriever().search(tuple(match.chunk for match in matches),query,50)
	found=sorted(found,key=lambda match:(-match.score,match.chunk.chunk_id))[:candidate_k]
	return tuple(replace(by_id[match.chunk.chunk_id],score=match.score,rank=rank,retrieval_method="keyword-v1")
		for rank,match in enumerate(found,1))
