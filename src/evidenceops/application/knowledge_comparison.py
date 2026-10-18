"""固定小语料的片段级检索对照；不把无答案题计入正例平均值。"""
import argparse
import json
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from evidenceops.application.hybrid_knowledge import fuse_rankings,keyword_ranking
from evidenceops.application.bm25_knowledge import bm25_ranking
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
	seen=set()
	# 全部输入先校验，避免后面的坏案例使前面的付费请求白跑。
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
	results=[]
	snapshot=None
	# 此对照专用于当前37片段小语料，超过50直接失败，不截断候选假装完整基线。
	service=VectorKnowledgeService(factory,max_candidates=50)
	for case in cases:
		relevant=frozenset(case["relevant_chunk_ids"])
		required=frozenset(case["required_chunk_ids"])
		started=perf_counter()
		ranked=service.search_many(document_ids,case["query"],provider,top_k=50)
		shared_cosine_seconds=perf_counter()-started
		current=sorted((match.chunk.chunk_id,match.embedding_set_id,match.config_fingerprint,match.chunk.content_hash) for match in ranked)
		if snapshot is not None and current!=snapshot: raise ValueError("评测期间发布集合发生变化，请固定集合后重试")
		snapshot=current
		if not relevant<={match.chunk.chunk_id for match in ranked}: raise ValueError("标注片段不属于当前发布集合，请重新审核版本")
		timings={"shared_load_encode_cosine_seconds":shared_cosine_seconds}
		stage_started=perf_counter()
		keyword=keyword_ranking(ranked,case["query"],candidate_k)
		timings["keyword_local_seconds"]=perf_counter()-stage_started
		stage_started=perf_counter()
		bm25=bm25_ranking(ranked,case["query"],candidate_k)
		timings["bm25_local_seconds"]=perf_counter()-stage_started
		stage_started=perf_counter()
		fused=fuse_rankings(ranked[:candidate_k],keyword,top_k)
		timings["keyword_rrf_local_seconds"]=perf_counter()-stage_started
		stage_started=perf_counter()
		bm25_fused=fuse_rankings(ranked[:candidate_k],bm25,top_k,keyword_name="bm25")
		timings["bm25_rrf_local_seconds"]=perf_counter()-stage_started
		result={"case_id":case["case_id"],"query":case["query"],"positive":bool(relevant),
			"relevant_chunk_ids":sorted(relevant),"required_chunk_ids":sorted(required),
			"shared_query_seconds":round(perf_counter()-started,4),"timings":timings,"modes":{}}
		for name,matches in (("cosine",ranked[:top_k]),("keyword",keyword[:top_k]),("bm25",bm25[:top_k]),("hybrid",fused),("hybrid_bm25",bm25_fused)):
			result["modes"][name]={**fragment_metrics(tuple(match.chunk.chunk_id for match in matches),relevant,required,top_k),
				"required_ranks":{identity:next((rank for rank,match in enumerate(matches,1) if match.chunk.chunk_id==identity),None) for identity in sorted(required)},
				"matches":[{"chunk_id":match.chunk.chunk_id,"document_id":match.document_id,"score":match.score,
					"rank":match.rank,"method":match.retrieval_method,"embedding_set_id":match.embedding_set_id,
					"config_fingerprint":match.config_fingerprint,"chunk_set_id":match.chunk.chunk_set.chunk_set_id,
					"content_hash":match.chunk.content_hash,"retrieval_details":match.retrieval_details} for match in matches]}
		results.append(result)
	positive=[result for result in results if result["positive"]]
	summary={}
	for name in ("cosine","keyword","bm25","hybrid","hybrid_bm25"):
		values=[result["modes"][name] for result in positive]
		critical=[value for value in values if value["required_hit"] is not None]
		summary[name]={key:sum(value[key] for value in values)/len(values) if values else None
			for key in ("precision_at_k","recall_at_k","reciprocal_rank")}
		summary[name].update(required_passes=sum(value["required_hit"] for value in critical),required_cases=len(critical))
		negative=[result["modes"][name] for result in results if not result["positive"]]
		summary[name].update(negative_nonempty_cases=sum(value["returned_count"]>0 for value in negative),negative_cases=len(negative))
	return {"top_k":top_k,"candidate_k":candidate_k,"rrf_constant":60,"bm25":{"k1":1.2,"b":0.75,"tokenizer":"word-or-han-char-v1"},"positive_cases":len(positive),"negative_cases":len(results)-len(positive),
		"snapshot":snapshot,"summary":summary,"results":results,"limitations":"人工片段标注需复核；同快照同查询向量，不评估生成/拒答；timings区分共享加载编码cosine与本地算法，不代表各配置独立端到端延迟；旧词频为子串匹配，BM25为词项匹配，差异不只评分公式"}


def main():
	parser=argparse.ArgumentParser(description="片段级cosine/BM25/RRF同题对照（最多50片段）")
	parser.add_argument("--manifest",type=Path,default=Path("samples/knowledge/manifest.json"))
	parser.add_argument("--cases",type=Path,default=Path("samples/knowledge/fragment_cases.json"))
	parser.add_argument("--top-k",type=int,default=3)
	parser.add_argument("--candidate-k",type=int,default=10)
	parser.add_argument("--output",type=Path,help="保存完整审计JSON；拒绝覆盖已有结果")
	args=parser.parse_args()
	if args.output is not None and args.output.exists(): raise ValueError("输出文件已存在，请选择新的实验文件名")
	started_at=datetime.now(timezone.utc).isoformat()
	manifest=read_manifest(args.manifest)
	manifest_hash=sha256(args.manifest.read_bytes()).hexdigest()
	if args.cases.stat().st_size>100000: raise ValueError("案例文件过大")
	case_bytes=args.cases.read_bytes()
	cases=json.loads(case_bytes.decode("utf-8-sig"))["cases"]
	engine=create_database_engine(DatabaseSettings.from_environment())
	try:
		result=compare_cases(create_session_factory(engine),tuple(item["document_id"] for item in manifest["documents"]),
			configured_embedding_provider(),cases,args.top_k,args.candidate_k)
		result["experiment"]={"started_at":started_at,"finished_at":datetime.now(timezone.utc).isoformat(),
			"cases_sha256":sha256(case_bytes).hexdigest(),"manifest_sha256":manifest_hash,
			"cases_file":args.cases.as_posix(),"manifest_file":args.manifest.as_posix()}
		if args.output is None:
			print(json.dumps(result,ensure_ascii=False,indent=2))
		else:
			# x模式防止并发覆盖；失败实验不会覆盖此前已完成的结果。
			with args.output.open("x",encoding="utf-8") as output:
				json.dump(result,output,ensure_ascii=False,indent=2)
			print(json.dumps({"output":args.output.as_posix(),"summary":result["summary"]},ensure_ascii=False,indent=2))
	finally: engine.dispose()


if __name__=="__main__": main()
