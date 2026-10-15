"""固定小语料的片段级检索对照；不把无答案题计入正例平均值。"""
import argparse
import json
from pathlib import Path
from time import perf_counter

from evidenceops.application.hybrid_knowledge import fuse_rankings,keyword_ranking
from evidenceops.application.knowledge_corpus_cli import read_manifest
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.knowledge_tools import configured_embedding_provider


def fragment_metrics(retrieved:tuple[str,...],relevant:frozenset[str],required:frozenset[str],top_k:int)->dict:
	if type(top_k) is not int or top_k<1: raise ValueError("top_k必须为正整数")
	if len(set(retrieved))!=len(retrieved) or len(retrieved)>top_k: raise ValueError("返回片段重复或超过top_k")
	if not required<=relevant: raise ValueError("必需片段必须属于相关片段")
	if not relevant:
		return {"precision_at_k":None,"recall_at_k":None,"reciprocal_rank":None,"required_hit":None,"returned_count":len(retrieved)}
	hits=len(set(retrieved)&relevant)
	first=next((rank for rank,identity in enumerate(retrieved,1) if identity in relevant),None)
	# 不足K仍以K作Precision分母；无答案题不能用召回为空冒充生成拒答。
	return {"precision_at_k":hits/top_k,"recall_at_k":hits/len(relevant),
		"reciprocal_rank":1/first if first else 0.0,"required_hit":required<=set(retrieved) if required else None,"returned_count":len(retrieved)}


def compare_cases(factory,document_ids,provider,cases,top_k=3,candidate_k=10)->dict:
	if type(top_k) is not int or not 1<=top_k<=50 or type(candidate_k) is not int or not top_k<=candidate_k<=50:
		raise ValueError("候选数与top_k无效")
	if not isinstance(cases,list) or not 1<=len(cases)<=100: raise ValueError("需要1到100个案例")
	results=[]
	seen=set()
	snapshot=None
	# 此对照专用于当前37片段小语料，超过50直接失败，不截断候选假装完整基线。
	service=VectorKnowledgeService(factory,max_candidates=50)
	for case in cases:
		if not isinstance(case,dict) or not isinstance(case.get("case_id"),str) or not case["case_id"].strip() or case["case_id"] in seen:
			raise ValueError("案例身份为空或重复")
		seen.add(case["case_id"])
		if not isinstance(case.get("query"),str) or not case["query"].strip(): raise ValueError("案例查询不能为空")
		for field in ("relevant_chunk_ids","required_chunk_ids"):
			labels=case.get(field)
			if not isinstance(labels,list) or any(not isinstance(identity,str) or not identity.strip() for identity in labels):
				raise ValueError("片段标注必须为非空身份列表")
			if len(set(labels))!=len(labels): raise ValueError("片段标注不能重复")
		relevant=frozenset(case["relevant_chunk_ids"])
		required=frozenset(case["required_chunk_ids"])
		if not required<=relevant: raise ValueError("必需片段必须属于相关片段")
		started=perf_counter()
		ranked=service.search_many(document_ids,case["query"],provider,top_k=50)
		current=sorted((match.chunk.chunk_id,match.embedding_set_id,match.config_fingerprint,match.chunk.content_hash) for match in ranked)
		if snapshot is not None and current!=snapshot: raise ValueError("评测期间发布集合发生变化，请固定集合后重试")
		snapshot=current
		if not relevant<={match.chunk.chunk_id for match in ranked}: raise ValueError("标注片段不属于当前发布集合，请重新审核版本")
		keyword=keyword_ranking(ranked,case["query"],candidate_k)
		fused=fuse_rankings(ranked[:candidate_k],keyword,top_k)
		result={"case_id":case["case_id"],"query":case["query"],"positive":bool(relevant),"shared_query_seconds":round(perf_counter()-started,4),"modes":{}}
		for name,matches in (("cosine",ranked[:top_k]),("hybrid",fused)):
			result["modes"][name]={**fragment_metrics(tuple(match.chunk.chunk_id for match in matches),relevant,required,top_k),
				"matches":[{"chunk_id":match.chunk.chunk_id,"document_id":match.document_id,"score":match.score,
					"rank":match.rank,"method":match.retrieval_method,"embedding_set_id":match.embedding_set_id,
					"config_fingerprint":match.config_fingerprint,"chunk_set_id":match.chunk.chunk_set.chunk_set_id,
					"content_hash":match.chunk.content_hash,"retrieval_details":match.retrieval_details} for match in matches]}
		results.append(result)
	positive=[result for result in results if result["positive"]]
	summary={}
	for name in ("cosine","hybrid"):
		values=[result["modes"][name] for result in positive]
		critical=[value for value in values if value["required_hit"] is not None]
		summary[name]={key:sum(value[key] for value in values)/len(values) if values else None
			for key in ("precision_at_k","recall_at_k","reciprocal_rank")}
		summary[name].update(required_passes=sum(value["required_hit"] for value in critical),required_cases=len(critical))
	return {"top_k":top_k,"candidate_k":candidate_k,"rrf_constant":60,"positive_cases":len(positive),"negative_cases":len(results)-len(positive),
		"snapshot":snapshot,"summary":summary,"results":results,"limitations":"开发题集、人工片段标注；同快照同查询向量，不评估生成/拒答；耗时为共用请求而非两种算法独立延迟"}


def main():
	parser=argparse.ArgumentParser(description="片段级cosine/RRF同题对照（最多50片段）")
	parser.add_argument("--manifest",type=Path,default=Path("samples/knowledge/manifest.json"))
	parser.add_argument("--cases",type=Path,default=Path("samples/knowledge/fragment_cases.json"))
	parser.add_argument("--top-k",type=int,default=3)
	parser.add_argument("--candidate-k",type=int,default=10)
	args=parser.parse_args()
	manifest=read_manifest(args.manifest)
	if args.cases.stat().st_size>100000: raise ValueError("案例文件过大")
	cases=json.loads(args.cases.read_text(encoding="utf-8-sig"))["cases"]
	engine=create_database_engine(DatabaseSettings.from_environment())
	try:
		result=compare_cases(create_session_factory(engine),tuple(item["document_id"] for item in manifest["documents"]),
			configured_embedding_provider(),cases,args.top_k,args.candidate_k)
		print(json.dumps(result,ensure_ascii=False,indent=2))
	finally: engine.dispose()


if __name__=="__main__": main()
