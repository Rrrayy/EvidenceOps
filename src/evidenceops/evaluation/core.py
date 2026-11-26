import json
import re
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from dataclasses import dataclass,field
from hashlib import sha256
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Callable
from uuid import uuid4

from evidenceops.application.diagnosis_response import to_response
from evidenceops.application.diagnosis_service import DiagnosisExecution
from evidenceops.domain.diagnosis_report import validate_report_evidence


@dataclass(frozen=True,slots=True)
class EvalCase:
	case_id:str
	description:str
	expected_status:str
	expected_error_code:str|None
	tool_calls:tuple[dict,...]
	required_sources:tuple[str,...]
	review_criteria:tuple[str,...]
	fixture_hashes:dict[str,str]
	expected_failure_stage:str="tool"
	evidence_checks:tuple[dict,...]=()
	expected_error_detail_code:str|None=None
	required_chunk_ids:tuple[str,...]=()
	retrieval_expectations:dict=field(default_factory=dict)
	review_context:dict=field(default_factory=dict)


def load_cases(path:Path)->tuple[EvalCase,...]:
	# 配置损坏必须停止，不能跳过坏案例并抬高通过率。
	payload=json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(payload,dict) or payload.get("schema_version")!=1:
		raise ValueError("评测集必须声明schema_version=1")
	items=payload.get("cases")
	if not isinstance(items,list) or not items:
		raise ValueError("评测集不能为空")
	cases=[]
	seen=set()
	for item in items:
		if not isinstance(item.get("required_chunk_ids",[]),list):
			raise ValueError("必需片段ID必须为数组")
		case=EvalCase(**{**item,"tool_calls":tuple(item["tool_calls"]),
			"required_sources":tuple(item["required_sources"]),"review_criteria":tuple(item["review_criteria"]),
			"evidence_checks":tuple(item.get("evidence_checks",[])),"required_chunk_ids":tuple(item.get("required_chunk_ids",[]))})
		if not isinstance(case.case_id,str) or not case.case_id.strip() or case.case_id in seen:
			raise ValueError("case_id不能为空或重复")
		if not isinstance(case.description,str) or not case.description.strip():
			raise ValueError("description不能为空")
		if any(not isinstance(value,str) or not value.strip() for value in case.required_chunk_ids) or len(set(case.required_chunk_ids))!=len(case.required_chunk_ids):
			raise ValueError("必需片段ID必须非空且不重复")
		if not isinstance(case.retrieval_expectations,dict) or not isinstance(case.review_context,dict):
			raise ValueError("检索预期和审核背景必须为对象")
		expected=case.retrieval_expectations
		if set(expected)-{"top_k","relevant_chunk_ids","document_ids","source_versions","chunk_set_ids","embedding_set_ids"}:
			raise ValueError("未知检索预期字段")
		if "top_k" in expected and (type(expected["top_k"]) is not int or not 1<=expected["top_k"]<=5):
			raise ValueError("评测top_k必须在1到5之间")
		for key in ("relevant_chunk_ids","document_ids","source_versions","chunk_set_ids","embedding_set_ids"):
			values=expected.get(key,[])
			if not isinstance(values,list) or any(not isinstance(value,str) or not value.strip() for value in values) or len(values)!=len(set(values)):
				raise ValueError("检索预期身份必须为不重复的字符串数组")
		if "relevant_chunk_ids" in expected and not set(case.required_chunk_ids)<=set(expected["relevant_chunk_ids"]):
			raise ValueError("必需片段必须属于相关片段")
		if case.expected_status not in ("succeeded","failed","cancelled"):
			raise ValueError("评测案例必须声明有效终态")
		if (case.expected_status=="failed")!=(isinstance(case.expected_error_code,str) and bool(case.expected_error_code.strip())):
			raise ValueError("失败案例必须声明错误码，成功案例错误码必须为空")
		if case.expected_status=="succeeded" and case.expected_error_code is not None:
			raise ValueError("成功案例不能声明错误码")
		for index,call in enumerate(case.tool_calls):
			if not isinstance(call,dict) or not isinstance(call.get("tool_name"),str) or not isinstance(call.get("arguments"),dict):
				raise ValueError("tool_calls必须包含工具名和参数对象")
			dependencies=call.get("depends_on",[])
			if type(call.get("strict_arguments",False)) is not bool:
				raise ValueError("strict_arguments必须为布尔值")
			query_terms=call.get("query_contains")
			if query_terms is not None and (call["tool_name"]!="search_knowledge" or "query" not in call["arguments"]
				or not isinstance(query_terms,list) or not 1<=len(query_terms)<=16
				or any(not isinstance(value,str) or not value.strip() or len(value)>100 for value in query_terms)
				or len({value.casefold() for value in query_terms})!=len(query_terms)):
				raise ValueError("query_contains只能为search_knowledge声明不重复的核心词数组")
			if not isinstance(dependencies,list) or any(type(value) is not int or value<0 or value>=index for value in dependencies) or len(set(dependencies))!=len(dependencies):
				raise ValueError("depends_on必须引用不重复的前置调用下标")
		if not 0<=len(case.tool_calls)<=16:
			raise ValueError("案例最多包含16个预期工具调用")
		if any(value not in ("log","metric","config","knowledge") for value in case.required_sources):
			raise ValueError("未知证据来源")
		if not case.review_criteria or any(not isinstance(value,str) or not value.strip() for value in case.review_criteria):
			raise ValueError("案例必须包含人工审核标准")
		if not isinstance(case.fixture_hashes,dict) or not case.fixture_hashes:
			raise ValueError("案例必须绑定样本指纹")
		if case.expected_failure_stage not in ("tool","collection","run"):
			raise ValueError("未知预期失败阶段")
		if case.expected_error_detail_code is not None and (not isinstance(case.expected_error_detail_code,str)
			or not case.expected_error_detail_code.strip() or case.expected_status not in ("failed","cancelled")):
			raise ValueError("内层错误码只能在失败案例声明")
		for expected in case.evidence_checks:
			if not isinstance(expected,dict) or expected.get("source") not in ("log","metric","config","knowledge"):
				raise ValueError("证据检查必须声明有效source")
			fragments=expected.get("summary_contains")
			if not isinstance(fragments,list) or not fragments or any(not isinstance(value,str) or not value for value in fragments):
				raise ValueError("证据检查必须包含非空摘要片段")
		seen.add(case.case_id)
		cases.append(case)
	return tuple(cases)


def matching_value(expected,actual)->bool:
	if type(expected) is not type(actual):
		return False
	if isinstance(expected,dict):
		return expected.keys()==actual.keys() and all(matching_value(value,actual[key]) for key,value in expected.items())
	if isinstance(expected,list):
		return len(expected)==len(actual) and all(matching_value(left,right) for left,right in zip(expected,actual))
	return expected==actual


def extract_visible_evidence_snapshots(messages:tuple[dict,...]|list[dict])->dict[str,str]:
	snapshots={}
	def collect(value):
		if isinstance(value,dict):
			identity=value.get("evidence_id")
			content=value.get("content")
			if isinstance(identity,str) and isinstance(content,str): snapshots[identity]=content
			for child in value.values(): collect(child)
		elif isinstance(value,list):
			for child in value: collect(child)
	for message in messages:
		content=message.get("content")
		if not isinstance(content,str): continue
		try:
			payload=json.loads(content)
			if message.get("role")=="tool" and isinstance(payload,dict):
				identity=payload.get("evidence_id")
				if isinstance(identity,str): snapshots[identity]=content
			collect(payload)
		except (ValueError,TypeError): continue
	return snapshots


def contains_query_terms(query:str,terms:list[str])->bool:
	if not isinstance(query,str):
		return False
	return all(re.search(r"(?<![A-Za-z0-9_])"+re.escape(term)+r"(?![A-Za-z0-9_])",query,re.IGNORECASE) is not None for term in terms)


def matches_tool_call(expected:dict,actual:dict)->bool:
	if expected.get("tool_name")!=actual.get("tool_name"):
		return False
	arguments=actual.get("arguments")
	if not isinstance(arguments,dict):
		return False
	query_terms=expected.get("query_contains")
	if expected.get("strict_arguments",False) and set(arguments)!=set(expected["arguments"]):
		return False
	for key,value in expected["arguments"].items():
		if key=="query" and query_terms is not None:
			if not contains_query_terms(arguments.get(key),query_terms):
				return False
		elif key not in arguments or not matching_value(value,arguments[key]):
			return False
	return True


def matched_call_count(expected:tuple[dict,...],actual:tuple[dict,...])->int:
	# 匹配使用增广路径，避免宽泛预期抢占只能匹配特定预期的调用。
	matched={}
	def assign(index:int,visited:set[int])->bool:
		call=expected[index]
		for position,item in enumerate(actual):
			if position in visited or not matches_tool_call(call,item):
				continue
			visited.add(position)
			if position not in matched or assign(matched[position],visited):
				matched[position]=index
				return True
		return False
	for index in range(len(expected)):
		assign(index,set())
	return len(matched)


def match_calls(expected:tuple[dict,...],actual:tuple[dict,...])->bool:
	return len(expected)==len(actual) and matched_call_count(expected,actual)==len(expected)


def match_dependencies(expected:tuple[dict,...],actual:tuple[dict,...])->bool:
	if len(expected)!=len(actual):
		return False
	assigned={}
	def assign(index:int,used:set[int])->bool:
		if index==len(expected):
			return True
		call=expected[index]
		for position,item in enumerate(actual):
			if position in used or not matches_tool_call(call,item):
				continue
			round_number=item.get("model_round")
			dependencies=call.get("depends_on",[])
			if dependencies and (type(round_number) is not int or any(
				type(actual[assigned[dependency]].get("model_round")) is not int
				or actual[assigned[dependency]]["model_round"]>=round_number for dependency in dependencies
			)):
				continue
			assigned[index]=position
			if assign(index+1,used|{position}):
				return True
			del assigned[index]
		return False
	return assign(0,set())


def final_context_audit(result:DiagnosisExecution):
	models=[item for item in result.execution_records if item.kind=="model"]
	if not models:
		return None
	last=models[-1]
	matches=[audit for audit in result.context_audits if audit.model_request_id==last.model_request_id and audit.model_round==last.model_round]
	return matches[0] if len(matches)==1 else None


def visible_snapshots(audit)->dict[str,str]:
	visible={}
	def collect(value):
		if isinstance(value,dict):
			if isinstance(value.get("evidence_id"),str) and isinstance(value.get("content"),str):
				visible[value["evidence_id"]]=value["content"]
			for child in value.values(): collect(child)
		elif isinstance(value,list):
			for child in value: collect(child)
	for message in audit.assembly.messages:
		try:
			collect(json.loads(message.get("content","")))
		except (TypeError,ValueError):
			continue
	return visible


def check_execution(case:EvalCase,result:DiagnosisExecution,observed_calls:tuple[dict,...]|None=None)->list[dict]:
	checks=[]
	def check(name:str,passed:bool)->None:
		checks.append({"name":name,"passed":passed})
	check("status",result.run.status.value==case.expected_status)
	check("error_code",result.run.error_code==case.expected_error_code)
	if case.expected_error_detail_code is not None:
		check("error_detail_code",(result.error_detail or {}).get("code")==case.expected_error_detail_code)
	check("report_presence",(result.report is not None)==(case.expected_status=="succeeded"))
	check("evidence_sources",set(case.required_sources).issubset({item.source.value for item in result.evidences}))
	check("evidence_ownership",all(item.run_id==result.run.run_id for item in result.evidences))
	check("evidence_unique",len({item.evidence_id for item in result.evidences})==len(result.evidences))
	check("evidence_content_hash",all(item.content_snapshot is None or sha256(item.content_snapshot.encode("utf-8")).hexdigest()==item.content_hash for item in result.evidences))
	audit=final_context_audit(result) if result.context_audits else None
	knowledge=[item for item in result.evidences if item.source.value=="knowledge"]
	tools=[item for item in result.execution_records if item.kind=="tool"]
	knowledge_calls=[item for item in tools if item.tool_name=="search_knowledge" and item.tool_call_id]
	check("knowledge_evidence_linked",all(any(item.evidence_id.startswith(f"{result.run.run_id}-{call.tool_call_id}-") for call in knowledge_calls) for item in knowledge))
	check("knowledge_evidence_source",all(item.source.value=="knowledge" for item in result.evidences
		if any(item.evidence_id.startswith(f"{result.run.run_id}-{call.tool_call_id}-") for call in knowledge_calls)))
	check("knowledge_evidence_metadata",all(item.content_snapshot is not None and item.source_version is not None
		and isinstance(item.source_metadata,dict) and all(item.source_metadata.get(key) is not None for key in
		("document_id","chunk_id","chunk_set_id","start_offset","end_offset","rank","retrieval_method")) for item in knowledge))
	if audit is not None:
		snapshots=visible_snapshots(audit)
		check("visible_evidence_snapshots",all(item.content_snapshot is None or snapshots.get(item.evidence_id)==item.content_snapshot
			for item in result.evidences if item.evidence_id in audit.assembly.visible_evidence_ids))
	for field,attribute in (("document_ids","document_id"),("chunk_set_ids","chunk_set_id"),("embedding_set_ids","embedding_set_id")):
		if field in case.retrieval_expectations:
			allowed=set(case.retrieval_expectations[field])
			check("retrieval_"+field,all(isinstance(item.source_metadata,dict) and item.source_metadata.get(attribute) in allowed for item in knowledge))
	if "source_versions" in case.retrieval_expectations:
		check("retrieval_source_versions",all(item.source_version in case.retrieval_expectations["source_versions"] for item in knowledge))
	if case.required_chunk_ids:
		top_k=case.retrieval_expectations.get("top_k")
		chunks={item.source_metadata.get("chunk_id") for item in knowledge
			if isinstance(item.source_metadata,dict) and (top_k is None or (type(item.source_metadata.get("rank")) is int and 1<=item.source_metadata["rank"]<=top_k))}
		check("required_chunks_retrieved",set(case.required_chunk_ids).issubset(chunks))
		visible=set(audit.assembly.visible_evidence_ids) if audit is not None else set()
		visible_chunks={item.source_metadata.get("chunk_id") for item in knowledge
			if item.evidence_id in visible and isinstance(item.source_metadata,dict) and item.source_metadata.get("chunk_id") in chunks}
		check("required_chunks_visible",audit is not None and set(case.required_chunk_ids).issubset(visible_chunks))
	check("record_ownership",all(item.run_id==result.run.run_id for item in result.execution_records))
	check("records_present",bool(result.execution_records) or not case.tool_calls)
	check("tool_allowlist",all(item.tool_name in {call["tool_name"] for call in case.tool_calls}
		for item in result.execution_records if item.kind=="tool"))
	tool_records=[item for item in result.execution_records if item.kind=="tool"]
	call_ids=[item.tool_call_id for item in tool_records]
	check("tool_call_ids_unique",all(isinstance(value,str) and value.strip() for value in call_ids)
		and len(set(call_ids))==len(call_ids))
	check("tool_call_count",len(tool_records)==len(case.tool_calls))
	actual=tuple({"tool_name":item.tool_name,"arguments":item.query_arguments,"model_round":item.model_round} for item in tool_records)
	if observed_calls is not None:
		observed_ids=[item.get("tool_call_id") for item in observed_calls]
		valid_ids=all(isinstance(value,str) and bool(value.strip()) for value in observed_ids)
		valid_ids=valid_ids and len(set(observed_ids))==len(observed_ids)
		observed_by_id={item["tool_call_id"]:item for item in observed_calls} if valid_ids else {}
		linked=valid_ids and len(tool_records)==len(observed_calls)
		linked=linked and all(item.tool_call_id in observed_by_id
			and observed_by_id[item.tool_call_id].get("tool_name")==item.tool_name for item in tool_records)
		check("tool_observations_linked",linked)
		actual=tuple({**observed_by_id[item.tool_call_id],"model_round":item.model_round} for item in tool_records) if linked else ()
	check("tool_calls_one_to_one",match_calls(case.tool_calls,actual))
	if any(call.get("depends_on") for call in case.tool_calls):
		check("tool_dependencies",match_dependencies(case.tool_calls,actual))
	if case.expected_status=="succeeded":
		check("tool_success",all(item.status=="succeeded" for item in result.execution_records if item.kind=="tool"))
	elif case.expected_failure_stage=="tool":
		check("failed_tool_record",any(item.kind=="tool" and item.status=="failed"
			and item.error_code==case.expected_error_code for item in result.execution_records))
	elif case.expected_failure_stage=="collection":
		# 空指标在Collector失败，不能错误要求成功的查询工具记录为failed。
		tool_records=[item for item in result.execution_records if item.kind=="tool"]
		check("collection_after_tool_success",bool(tool_records) and all(item.status=="succeeded" for item in tool_records))
	for index,expected in enumerate(case.tool_calls):
		# 同名工具允许多次调用；参数类型也要匹配，避免 True 冒充整数 1。
		matching=[item.query_arguments for item in result.execution_records if item.kind=="tool" and item.tool_name==expected["tool_name"]]
		if observed_calls is not None:
			matching=[item.get("arguments") for item in actual if item.get("tool_name")==expected["tool_name"]]
		check(f"tool_parameters_{index}",any(item is not None and matches_tool_call(expected,
			{"tool_name":expected["tool_name"],"arguments":item}) for item in matching))
	for index,expected in enumerate(case.evidence_checks):
		check(f"evidence_content_{index}",any(item.source.value==expected["source"]
			and all(fragment in item.summary for fragment in expected["summary_contains"]) for item in result.evidences))
	if result.report is not None:
		try:
			validate_report_evidence(result.report,result.evidences)
			valid=result.report.run_id==result.run.run_id
		except (ValueError,TypeError):
			valid=False
		check("report_references",valid)
		if result.context_audits or case.required_chunk_ids:
			visible=set(audit.assembly.visible_evidence_ids) if audit is not None else set()
			claims=(result.report.root_cause,)+tuple(result.report.recommendations)
			check("report_references_visible",audit is not None and all(set(claim.evidence_ids).issubset(visible) for claim in claims))
	return checks


def summarize_results(results:list[dict])->dict:
	# 自动契约结果与报告语义审核分开统计，不合成单一通过率。
	if not isinstance(results,list) or not results:
		raise ValueError("评测结果不能为空")
	for item in results:
		if not isinstance(item,dict) or type(item.get("rule_passed")) is not bool:
			raise ValueError("案例必须包含布尔类型的rule_passed")
	count=len(results)
	rule_count=sum(item["rule_passed"] for item in results)
	semantic_reviews=[item.get("semantic_review",{}) for item in results]
	for review in semantic_reviews:
		if not isinstance(review,dict) or review.get("status","pending") not in ("pending","passed","failed","disputed"):
			raise ValueError("兼容性审核状态无效")
		workflow=review.get("workflow_status")
		if workflow is not None and workflow not in ("execution_only","pending","single_reviewer","consensus","disputed","adjudicated"):
			raise ValueError("语义审核工作流状态无效")
	return {
		"case_count":count,"rule_passed_count":rule_count,"rule_pass_rate":rule_count/count,
		"execution_error_count":sum(item.get("execution_error") is not None for item in results),
		"semantic_review_pending":sum(review.get("workflow_status",review.get("status","pending"))=="pending" for review in semantic_reviews),
		"semantic_review_disputed":sum(review.get("workflow_status")=="disputed" for review in semantic_reviews),
		"semantic_review_execution_only":sum(review.get("workflow_status")=="execution_only" for review in semantic_reviews),
	}


def evaluation_metrics(case:EvalCase,execution:DiagnosisExecution,observed_calls:tuple[dict,...]|None)->dict:
	tools=[item for item in execution.execution_records if item.kind=="tool"]
	search_calls=[item for item in tools if item.tool_name=="search_knowledge"]
	successful_searches=[item for item in search_calls if item.status=="succeeded"]
	retrieval_status="not_attempted" if not search_calls else "failed" if not successful_searches else (
		"complete" if len(successful_searches)==len(search_calls) else "partial")
	by_id={item.get("tool_call_id"):item for item in observed_calls or ()}
	actual=tuple({"tool_name":item.tool_name,"arguments":by_id.get(item.tool_call_id,{}).get("arguments",item.query_arguments),
		"model_round":item.model_round} for item in tools)
	matched=matched_call_count(case.tool_calls,actual)
	precision=matched/len(actual) if actual else None
	recall=matched/len(case.tool_calls) if case.tool_calls else None
	f1=2*precision*recall/(precision+recall) if precision is not None and recall is not None and precision+recall else (0.0 if precision is not None and recall is not None else None)
	knowledge=[item for item in execution.evidences if item.source.value=="knowledge" and isinstance(item.source_metadata,dict)]
	top_k=case.retrieval_expectations.get("top_k")
	chunks={item.source_metadata.get("chunk_id") for item in knowledge if top_k is None or
		(type(item.source_metadata.get("rank")) is int and 1<=item.source_metadata["rank"]<=top_k)}
	required=set(case.required_chunk_ids)
	audit=final_context_audit(execution) if execution.context_audits else None
	visible=set(audit.assembly.visible_evidence_ids) if audit is not None else None
	visible_chunks={item.source_metadata.get("chunk_id") for item in knowledge if visible is not None and item.evidence_id in visible}
	claims=() if execution.report is None else (execution.report.root_cause,)+tuple(execution.report.recommendations)
	references=[identity for claim in claims for identity in claim.evidence_ids]
	valid_ids={item.evidence_id for item in execution.evidences if item.run_id==execution.run.run_id}
	models=[item for item in execution.execution_records if item.kind=="model"]
	errors=[abs(item.estimated_input_tokens-item.reported_input_tokens)/item.reported_input_tokens for item in models
		if type(item.estimated_input_tokens) is int and type(item.reported_input_tokens) is int and item.reported_input_tokens>0 and item.usage_status=="complete"]
	return {"tool_matched":matched,"tool_expected":len(case.tool_calls),"tool_actual":len(actual),
		"tool_precision":precision,"tool_recall":recall,"tool_f1":f1,
		"extra_calls":max(0,len(actual)-matched),"missing_calls":max(0,len(case.tool_calls)-matched),
		"duplicate_call_ids":len(tools)-len({item.tool_call_id for item in tools}),
		"dependency_order_valid":match_dependencies(case.tool_calls,actual) if any(item.get("depends_on") for item in case.tool_calls) else None,
		"retrieval_status":retrieval_status,
		"required_chunk_recall":len(required&chunks)/len(required) if required and successful_searches else None,
		"relevant_chunk_recall":len(set(case.retrieval_expectations.get("relevant_chunk_ids",[]))&chunks)/len(case.retrieval_expectations["relevant_chunk_ids"]) if case.retrieval_expectations.get("relevant_chunk_ids") and successful_searches else None,
		"context_recall":len(required&visible_chunks)/len(required) if required and successful_searches and visible is not None else None,
		"reference_count":len(references),"valid_reference_count":sum(identity in valid_ids for identity in references),
		"visible_reference_count":sum(identity in visible for identity in references) if visible is not None else None,
		"token_relative_errors":errors}


def aggregate_metrics(results:list[dict])->dict:
	metrics=[item["metrics"] for item in results if item.get("metrics") is not None]
	def average(name):
		values=[item[name] for item in metrics if item.get(name) is not None]
		return sum(values)/len(values) if values else None
	durations=sorted(item["wall_duration_ms"] for item in results)
	def percentile(fraction):
		return durations[max(0,ceil(fraction*len(durations))-1)] if durations else None
	references=sum(item["reference_count"] for item in metrics)
	visible=[item for item in metrics if item["visible_reference_count"] is not None]
	errors=[value for item in metrics for value in item["token_relative_errors"]]
	return {"cases_with_metrics":len(metrics),"mean_tool_precision":average("tool_precision"),
		"mean_tool_recall":average("tool_recall"),"mean_tool_f1":average("tool_f1"),
		"retrieval_status_counts":{status:sum(item.get("retrieval_status")==status for item in metrics)
			for status in ("not_attempted","failed","partial","complete")},
		"extra_call_cases":sum(item["extra_calls"]>0 for item in metrics),
		"extra_call_rate":sum(item["extra_calls"]>0 for item in metrics)/len(metrics) if metrics else None,
		"duplicate_id_cases":sum(item["duplicate_call_ids"]>0 for item in metrics),
		"duplicate_id_rate":sum(item["duplicate_call_ids"]>0 for item in metrics)/len(metrics) if metrics else None,
		"order_violations":sum(item["dependency_order_valid"] is False for item in metrics),
		"parameter_match_rate":sum(item["tool_matched"] for item in metrics)/sum(item["tool_expected"] for item in metrics) if sum(item["tool_expected"] for item in metrics) else None,
		"invalid_references":sum(item["reference_count"]-item["valid_reference_count"] for item in metrics),
		"required_chunk_recall":average("required_chunk_recall"),"relevant_chunk_recall":average("relevant_chunk_recall"),"context_recall":average("context_recall"),
		"valid_reference_rate":sum(item["valid_reference_count"] for item in metrics)/references if references else None,
		"visible_reference_rate":sum(item["visible_reference_count"] for item in visible)/sum(item["reference_count"] for item in visible) if sum(item["reference_count"] for item in visible) else None,
		"mean_token_relative_error":sum(errors)/len(errors) if errors else None,
		"latency_ms_p50":percentile(.5),"latency_ms_p95":percentile(.95),"latency_ms_p99":percentile(.99)}


def attach_retrieval_comparison(report:dict,comparison:dict)->None:
	if not isinstance(comparison,dict) or not isinstance(comparison.get("results"),list) or not isinstance(comparison.get("snapshot"),list):
		raise ValueError("检索对照结果缺少案例或集合快照")
	snapshot={tuple(item) for item in comparison["snapshot"] if isinstance(item,list) and len(item)==4}
	for item in report["results"]:
		matches=[entry for entry in comparison["results"] if entry.get("query")==item["input"]]
		if len(matches)!=1:
			item["retrieval_comparison"]={"status":"unavailable","reason":"查询无法唯一匹配"}
			continue
		identities={(entry["source_metadata"].get("chunk_id"),entry["source_metadata"].get("embedding_set_id"),
			entry["source_metadata"].get("config_fingerprint"),entry["content_hash"]) for entry in item["knowledge_evidence"]}
		if not identities or not identities<=snapshot or comparison.get("top_k")!=item["retrieval_expectations"].get("top_k"):
			item["retrieval_comparison"]={"status":"unavailable","reason":"没有检索结果或集合、Top-K 不一致"}
			continue
		item["retrieval_comparison"]={"status":"available","modes":matches[0].get("modes",{}),
			"experiment":comparison.get("experiment"),"top_k":comparison["top_k"]}


def summarize_usage(records:tuple)->dict:
	models=[record for record in records if record.kind=="model"]
	complete=[record for record in models if record.usage_status=="complete" and all(
		type(value) is int and value>=0 for value in
		(record.reported_input_tokens,record.reported_output_tokens,record.reported_total_tokens))]
	estimated=[record.estimated_input_tokens for record in models if type(record.estimated_input_tokens) is int and record.estimated_input_tokens>=0]
	return {
		"model_calls":len(models),"tool_calls":sum(record.kind=="tool" for record in records),
		"rounds":[{"model_round":record.model_round,"model_request_id":record.model_request_id,
			"usage_status":record.usage_status or "unknown","estimated_input_tokens":record.estimated_input_tokens,
			"reported_input_tokens":record.reported_input_tokens,"reported_output_tokens":record.reported_output_tokens,
			"reported_total_tokens":record.reported_total_tokens} for record in models],
		"reported_calls":len(complete),"unknown_calls":len(models)-len(complete),
		"reported_input_tokens":sum(record.reported_input_tokens for record in complete) if complete else None,
		"reported_output_tokens":sum(record.reported_output_tokens for record in complete) if complete else None,
		"reported_total_tokens":sum(record.reported_total_tokens for record in complete) if complete else None,
		"estimated_input_tokens":sum(estimated) if estimated else None,
		"estimated_input_calls":len(estimated),
		"status":"complete" if models and len(complete)==len(models) else ("partial" if complete else "unknown"),
	}


def validate_pricing(pricing:dict)->tuple[Decimal,Decimal]:
	if not isinstance(pricing,dict):
		raise ValueError("价格配置必须是JSON对象")
	try:
		input_price=Decimal(str(pricing["input_per_million"]))
		output_price=Decimal(str(pricing["output_per_million"]))
		if not all(value.is_finite() and value>=0 for value in (input_price,output_price)):
			raise ValueError("价格必须为有限非负数")
		if not all(isinstance(pricing[key],str) and pricing[key].strip() for key in ("model","currency","version")):
			raise ValueError("价格必须包含模型、币种和版本")
		return input_price,output_price
	except (KeyError,InvalidOperation,TypeError) as error:
		raise ValueError("价格配置无效") from error


def calculate_cost(usage:dict|None,pricing:dict|None)->dict|None:
	if pricing is None:
		return None
	input_price,output_price=validate_pricing(pricing)
	if usage is None or usage["status"]!="complete":
		return None
	amount=(input_price*usage["reported_input_tokens"]+output_price*usage["reported_output_tokens"])/Decimal(1000000)
	return {"amount":str(amount),"currency":pricing["currency"],"pricing_version":pricing["version"],
		"model":pricing["model"],"kind":"estimate_from_reported_tokens"}


def run_suite(cases:tuple[EvalCase,...],factory:Callable,mode:str,pricing:dict|None=None,references:dict|None=None)->dict:
	# 每个案例独立创建资源，避免 Mock 游标和运行状态污染后续案例。
	if not cases or mode not in ("mock","real"):
		raise ValueError("需要非空案例及mock/real模式")
	if pricing is not None:
		validate_pricing(pricing)
	results=[]
	batch_id=f"eval-{uuid4()}"
	for case in cases:
		started=perf_counter()
		checks=[]
		response=None
		usage=None
		context_audits=[]
		model_requests=[]
		knowledge_evidence=[]
		metrics=None
		error=None
		try:
			with factory(case) as service:
				execution=service.execute(f"{batch_id}-{case.case_id}",case.description)
				checks=check_execution(case,execution,getattr(service,"observed_calls",None))
				response=to_response(execution)
				usage=summarize_usage(execution.execution_records)
				metrics=evaluation_metrics(case,execution,getattr(service,"observed_calls",None))
				model_requests=[deepcopy(item) for item in getattr(service,"observed_model_requests",())]
				known_evidence_ids={item["evidence_id"] for item in response["evidences"]}
				for request in model_requests:
					request["visible_evidence_ids"]=[identity for identity in request.pop("evidence_id_mentions",()) if identity in known_evidence_ids]
					request["visible_evidence_snapshots"]={identity:content for identity,content in
						extract_visible_evidence_snapshots(request["messages"]).items() if identity in known_evidence_ids}
				context_audits=[{"model_round":audit.model_round,"model_request_id":audit.model_request_id,
					"visible_evidence_ids":list(audit.assembly.visible_evidence_ids),
					"messages":list(audit.assembly.messages),
					"estimated_input_tokens":audit.assembly.estimated_input_tokens,
					"estimator_id":audit.assembly.estimator_id,"omissions":list(audit.assembly.omissions)}
					for audit in execution.context_audits]
				knowledge_evidence=[{"evidence_id":item.evidence_id,"source_version":item.source_version,
					"content_hash":item.content_hash,"content_snapshot":item.content_snapshot,
					"source_metadata":item.source_metadata} for item in execution.evidences if item.source.value=="knowledge"]
		except Exception as exception:
			# 不输出原始异常以免泄露凭据；异常案例仍保留在通过率分母中。
			error=type(exception).__name__
		# 规则通过不等于语义正确；审核保留 pending，未知 usage 不填零。
		semantic_review={"status":"pending","criteria":list(case.review_criteria),"reviews":[]}
		if response is None or response.get("report") is None:
			semantic_review["workflow_status"]="execution_only"
		else:
			semantic_review["workflow_status"]="pending"
		if references is not None and case.case_id in references:
			semantic_review["reference_standard"]=references[case.case_id]
		results.append({
			"case_id":case.case_id,"checks":checks,"execution_error":error,
			"input":case.description,"fixture_hashes":case.fixture_hashes,
			"rule_passed":error is None and bool(checks) and all(item["passed"] for item in checks),
			"wall_duration_ms":(perf_counter()-started)*1000,
			"semantic_review":semantic_review,
			"review_context":case.review_context,"retrieval_expectations":case.retrieval_expectations,
			"context_audits":context_audits,"model_requests":model_requests,
			"knowledge_evidence":knowledge_evidence,"metrics":metrics,
			"token_usage":usage,"cost":calculate_cost(usage,pricing) if pricing is not None and response is not None
				and (execution.model_config or {}).get("model_id")==pricing.get("model") else None,"response":response,
		})
	from evidenceops.evaluation.review import summarize_semantic_reviews
	return {
		"schema_version":1,"batch_id":batch_id,"mode":mode,
		"summary":summarize_results(results),
		"semantic_quality":summarize_semantic_reviews(results),
		"metrics":aggregate_metrics(results),
		"results":results,
	}
