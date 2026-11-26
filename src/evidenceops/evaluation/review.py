import json
import os
import re
import tempfile
import shutil
import unicodedata
from datetime import datetime,timezone
from hashlib import sha256
from itertools import combinations
from pathlib import Path
from typing import Callable

from evidenceops.evaluation.core import extract_visible_evidence_snapshots,load_cases,summarize_results


CLAIM_JUDGEMENTS={"supported","partially_supported","unsupported","evidence_conflict","indeterminate"}
EVIDENCE_RELATIONS={"supports","contradicts","context_only","not_relevant"}
FACT_COVERAGE={"covered","partial","missing","not_applicable"}
CASE_COMPLETENESS={"complete","partially_complete","incomplete"}
ANSWERABILITY={"appropriate","overclaim","unnecessary_abstention","indeterminate"}
EXPECTED_ACTION_LABELS={"answer":"依据证据回答用户问题","abstain":"证据不足或请求无效时不生成诊断结论","not_applicable":"不适用"}

REVIEW_BINDING_FIELDS=("blind_batch_token","source_result_sha256","case_file_sha256","reference_file_sha256",
	"prompt_template_sha256","corpus_snapshot_sha256","model_config_sha256")


def canonical_hash(value)->str:
	canonical=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
	return sha256(canonical.encode("utf-8")).hexdigest()


def file_hash(path:Path)->str:
	return sha256(path.read_bytes()).hexdigest()


def load_reference_standards(path:Path)->dict:
	payload=json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(payload,dict) or payload.get("schema_version")!=1 or not isinstance(payload.get("cases"),list):
		raise ValueError("参考标准文件必须包含schema_version=1及cases数组")
	standards={}
	allowed_actions={"answer","abstain","not_applicable"}
	for item in payload["cases"]:
		if not isinstance(item,dict) or not isinstance(item.get("case_id"),str) or not item["case_id"].strip():
			raise ValueError("参考标准缺少有效case_id")
		if item["case_id"] in standards: raise ValueError("参考标准case_id重复")
		if item.get("expected_action") not in allowed_actions: raise ValueError("参考标准expected_action无效")
		if not isinstance(item.get("scenario"),str) or not item["scenario"].strip(): raise ValueError("参考标准scenario不能为空")
		for field in ("required_facts","acceptable_conclusions","prohibited_inferences"):
			values=item.get(field)
			if not isinstance(values,list): raise ValueError("参考标准"+field+"必须为数组")
			if field=="required_facts":
				fact_ids=set()
				for fact in values:
					if (not isinstance(fact,dict) or not isinstance(fact.get("fact_id"),str) or not fact["fact_id"].strip()
						or not isinstance(fact.get("text"),str) or not fact["text"].strip()): raise ValueError("required_facts项无效")
					if fact["fact_id"] in fact_ids: raise ValueError("required_facts的fact_id重复")
					fact_ids.add(fact["fact_id"])
			elif any(not isinstance(value,str) or not value.strip() for value in values):
				raise ValueError("参考结论应为非空字符串")
		standards[item["case_id"]]=item
	return standards


def load_reference_document(path:Path)->dict:
	payload=json.loads(path.read_text(encoding="utf-8-sig"))
	load_reference_standards(path)
	gaps=payload.get("coverage_gaps",[])
	if not isinstance(gaps,list) or any(not isinstance(item,dict) or not isinstance(item.get("scenario"),str)
		or not isinstance(item.get("status"),str) or not isinstance(item.get("reason"),str) for item in gaps):
		raise ValueError("coverage_gaps必须是带scenario、status、reason的数组")
	return payload


def report_claims(item:dict)->list[dict]:
	response=item.get("response") or {}
	report=response.get("report")
	if report is None: return []
	claims=[]
	root=report.get("root_cause")
	if isinstance(root,dict): claims.append({"claim_id":"root_cause","text":root.get("text"),"evidence_ids":root.get("evidence_ids",[])})
	for index,claim in enumerate(report.get("recommendations",[]),1):
		claims.append({"claim_id":f"recommendation_{index}","text":claim.get("text"),"evidence_ids":claim.get("evidence_ids",[])})
	return claims


def review_binding(batch:dict)->dict:
	return {field:batch.get(field) for field in REVIEW_BINDING_FIELDS}


def case_review_binding(batch:dict,item:dict)->dict:
	response=item.get("response") or {}
	return {**review_binding(batch),"run_id":response.get("run_id"),
		"model_config_sha256":canonical_hash(response.get("model_config"))}


def final_model_visibility(item:dict)->dict:
	response=item.get("response") or {}
	records=[record for record in response.get("execution_records",[]) if record.get("kind")=="model"]
	last=records[-1] if records else None
	request_id=last.get("model_request_id") if last else None
	for request in reversed(item.get("model_requests",[])):
		if request.get("request_id")==request_id:
			return {"status":"known","model_request_id":request_id,
				"evidence_ids":list(request.get("visible_evidence_ids",[])),
				"content_snapshots":dict(request.get("visible_evidence_snapshots",{})),"source":"captured_model_request"}
	for audit in reversed(item.get("context_audits",[])):
		if audit.get("model_request_id")==request_id:
			return {"status":"known","model_request_id":request_id,
				"evidence_ids":list(audit.get("visible_evidence_ids",[])),
				"content_snapshots":extract_visible_evidence_snapshots(audit.get("messages",[])),"source":"context_audit"}
	return {"status":"unknown","model_request_id":request_id,"evidence_ids":[],"content_snapshots":{},"source":"not_captured"}


def evidence_manifest(item:dict)->list[dict]:
	response=item.get("response") or {}
	return sorted(({"evidence_id":evidence.get("evidence_id"),"source":evidence.get("source"),
		"source_version":evidence.get("source_version"),"content_hash":evidence.get("content_hash"),
		"source_ref":evidence.get("source_ref"),"source_metadata":evidence.get("source_metadata")}
		for evidence in response.get("evidences",[])),key=lambda value:str(value["evidence_id"]))


def validate_workspace_fixtures(cases_path:Path,cases:tuple)->list[dict]:
	project_root=Path(__file__).resolve().parents[3]
	checks=[]
	for case in cases:
		for relative,expected in case.fixture_hashes.items():
			path=(project_root/relative).resolve()
			if not path.is_relative_to(project_root):
				checks.append({"case_id":case.case_id,"path":relative,"expected_sha256":expected,"status":"unsafe_path"})
				continue
			if not path.is_file():
				checks.append({"case_id":case.case_id,"path":relative,"expected_sha256":expected,"status":"missing"})
				continue
			actual=file_hash(path)
			checks.append({"case_id":case.case_id,"path":relative,"expected_sha256":expected,
				"actual_sha256":actual,"status":"matches" if actual==expected else "mismatch"})
	return checks


def freeze_review_batch(result_path:Path,cases_path:Path,references_path:Path,output_path:Path)->dict:
	if output_path.exists(): raise ValueError("输出文件已存在，不能覆盖已冻结批次")
	payload=load_result(result_path)
	if payload.get("review_batch") is not None: raise ValueError("该结果已经冻结")
	cases=load_cases(cases_path)
	case_map={case.case_id:case for case in cases}
	standards=load_reference_standards(references_path)
	result_ids=[item["case_id"] for item in payload["results"]]
	if len(set(result_ids))!=len(result_ids) or set(result_ids)-set(case_map): raise ValueError("评测结果与案例文件身份不匹配")
	if set(result_ids)-set(standards): raise ValueError("部分评测案例缺少人工参考标准")
	seen_runs=set()
	corpus_rows=[]
	models=set()
	visible_count=0
	for item in payload["results"]:
		case=case_map[item["case_id"]]
		if item.get("fixture_hashes")!=case.fixture_hashes: raise ValueError("结果中的样本指纹与案例定义不一致："+case.case_id)
		response=item.get("response") or {}
		run_id=response.get("run_id")
		if response and (not isinstance(run_id,str) or not run_id.strip()): raise ValueError("Run缺少稳定身份："+case.case_id)
		if run_id in seen_runs: raise ValueError("评测结果中Run ID重复")
		if run_id: seen_runs.add(run_id)
		report=response.get("report")
		if report is not None:
			if report.get("run_id")!=run_id: raise ValueError("报告不属于对应Run："+case.case_id)
			evidence_ids={evidence.get("evidence_id") for evidence in response.get("evidences",[])}
			if any(not set(claim["evidence_ids"])<=evidence_ids for claim in report_claims(item)):
				raise ValueError("报告引用了当前Run不存在的Evidence："+case.case_id)
			item["semantic_review"]["workflow_status"]="pending"
		else:
			item["semantic_review"]["workflow_status"]="execution_only"
		item["semantic_review"]["reference_standard"]=standards[case.case_id]
		item["semantic_review"]["model_visibility"]=final_model_visibility(item)
		if item["semantic_review"]["model_visibility"]["status"]=="known": visible_count+=1
		model_id=(response.get("model_config") or {}).get("model_id")
		if model_id: models.add(model_id)
		corpus_rows.append({"case_id":case.case_id,"fixture_hashes":case.fixture_hashes,"evidence":evidence_manifest(item)})
	prompt_hash=None
	prompt_provenance="not_recorded_for_historical_runs"
	source_batch=payload.get("evaluation_batch")
	case_file_provenance="not_recorded_for_historical_runs"
	if isinstance(source_batch,dict):
		prompt_hash=source_batch.get("prompt_template_sha256")
		if prompt_hash: prompt_provenance="captured_during_evaluation"
		case_snapshot=(source_batch.get("case_file") or {}).get("sha256")
		case_file_provenance="captured_during_evaluation" if case_snapshot==file_hash(cases_path) else "recorded_hash_mismatch"
	else:
		try:
			from evidenceops.application.agent_loop import AgentLoop
			import inspect
			prompt_hash=sha256(inspect.getsource(AgentLoop._build_history).encode("utf-8")).hexdigest()
			prompt_provenance="current_source_fingerprint_historical_match_unverified"
		except (OSError,TypeError):
			prompt_provenance="unavailable"
	batch={
		"schema_version":1,"frozen_at":datetime.now(timezone.utc).isoformat(),
		"source_result":{"path":result_path.name,"sha256":file_hash(result_path),"batch_id":payload.get("batch_id")},
		"case_file":{"path":cases_path.as_posix(),"sha256":file_hash(cases_path)},
		"case_file_provenance":case_file_provenance,
		"reference_file":{"path":references_path.as_posix(),"sha256":file_hash(references_path)},
	"batch_id":payload.get("batch_id"),"model_ids":sorted(models),
		"blind_batch_token":canonical_hash({"batch_id":payload.get("batch_id"),"source_result_sha256":file_hash(result_path)}),
	"model_config_sha256":canonical_hash(sorted(((item.get("response") or {}).get("model_config") for item in payload["results"]),key=lambda value:json.dumps(value,sort_keys=True))),
		"prompt_template_sha256":prompt_hash,"prompt_provenance":prompt_provenance,
		"corpus_snapshot_sha256":canonical_hash(corpus_rows),"corpus_manifest":corpus_rows,
		"workspace_fixture_validation":validate_workspace_fixtures(cases_path,cases),
		"report_eligible_cases":sum(bool((item.get("response") or {}).get("report")) for item in payload["results"]),
		"execution_only_cases":sum(not bool((item.get("response") or {}).get("report")) for item in payload["results"]),
		"model_visibility_known_cases":visible_count,
		"comparison_ready":prompt_provenance=="captured_during_evaluation"
			and case_file_provenance=="captured_during_evaluation"
			and all(entry["status"]=="matches" for entry in validate_workspace_fixtures(cases_path,cases))
			and visible_count==sum(bool((item.get("response") or {}).get("report")) for item in payload["results"]),
		"reference_coverage_gaps":load_reference_document(references_path).get("coverage_gaps",[]),
	}
	for item in payload["results"]:
		item["semantic_review"]["batch_binding"]=case_review_binding(batch,item)
	payload["review_batch"]=batch
	refresh_review_summary(payload)
	write_json_new(output_path,payload)
	return payload


def attach_review_batch_metadata(report:dict,cases_path:Path,references_path:Path,prompt_hash:str|None,revision:str|None)->None:
	corpus_rows=[]
	models=set()
	for item in report.get("results",[]):
		response=item.get("response") or {}
		model_id=(response.get("model_config") or {}).get("model_id")
		if model_id: models.add(model_id)
		corpus_rows.append({"case_id":item["case_id"],"fixture_hashes":item.get("fixture_hashes",{}),"evidence":evidence_manifest(item)})
	report["evaluation_batch"]={"case_file":{"path":cases_path.as_posix(),"sha256":file_hash(cases_path)},
		"reference_file":{"path":references_path.as_posix(),"sha256":file_hash(references_path)},
		"model_ids":sorted(models),"model_config_sha256":canonical_hash(sorted(((item.get("response") or {}).get("model_config") for item in report.get("results",[])),key=lambda value:json.dumps(value,sort_keys=True))),
		"prompt_template_sha256":prompt_hash,"source_revision":revision,
		"corpus_snapshot_sha256":canonical_hash(corpus_rows)}
	report["semantic_quality"]=summarize_semantic_reviews(report.get("results",[]))
	report["semantic_quality"]["reference_coverage_gaps"]=load_reference_document(references_path).get("coverage_gaps",[])


def import_reviews(result_path:Path,review_path:Path)->dict:
	original_hash=file_hash(result_path)
	payload=load_result(result_path)
	data=json.loads(review_path.read_text(encoding="utf-8-sig"))
	if not isinstance(data,dict) or data.get("schema_version")!=1 or not isinstance(data.get("reviews"),list):
		raise ValueError("人工审核文件必须声明schema_version=1及reviews数组")
	batch=payload.get("review_batch")
	if not isinstance(batch,dict): raise ValueError("先冻结评测批次，才能导入人工审核")
	if data.get("batch_binding")!=review_binding(batch): raise ValueError("审核文件绑定的批次快照与结果不一致")
	reviewer=data.get("reviewer")
	role=data.get("role")
	if not isinstance(reviewer,str) or not reviewer.strip() or role not in ("independent","adjudicator"):
		raise ValueError("审核者身份或角色无效")
	by_id={item["case_id"]:item for item in payload["results"]}
	prepared=[]
	seen=set()
	for review in data["reviews"]:
		if not isinstance(review,dict): raise ValueError("单题审核必须为对象")
		identity=review.get("case_id")
		if identity not in by_id or identity in seen: raise ValueError("审核案例不存在或在文件内重复")
		seen.add(identity)
		item=by_id[identity]
		validated=validate_review_record(review,item,reviewer,role)
		existing=item["semantic_review"].get("reviews",[])
		if any(entry.get("reviewer")==reviewer for entry in existing): raise ValueError("该评审者已审核此案例")
		if role=="adjudicator" and (not has_disagreement(existing) or any(entry.get("role")=="adjudicator" for entry in existing)):
			raise ValueError("仅有未解决的双人分歧时才能仲裁，且每题只能仲裁一次")
		prepared.append((item,validated))
	if file_hash(result_path)!=original_hash: raise ValueError("批次结果已被其他审核更新，请重新加载审核文件")
	for item,validated in prepared:
		item["semantic_review"].setdefault("reviews",[]).append({"reviewer":reviewer,"role":role,
			"reviewed_at":validated.pop("reviewed_at"),"batch_binding":review_binding(batch),**validated})
	refresh_review_summary(payload)
	save_result(result_path,payload)
	return payload


def load_result(path:Path)->dict:
	payload=json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(payload,dict) or payload.get("schema_version")!=1:
		raise ValueError("评测结果必须声明schema_version=1")
	if not isinstance(payload.get("summary",{}),dict):
		raise ValueError("summary必须是对象")
	summarize_results(payload.get("results"))
	seen=set()
	# 开始交互前校验全部案例，避免审核到一半才发现文件结构损坏。
	for item in payload["results"]:
		case_id=item.get("case_id")
		if not isinstance(case_id,str) or not case_id.strip() or case_id in seen:
			raise ValueError("case_id不能为空或重复")
		if not isinstance(item.get("input"),str) or not item["input"].strip():
			raise ValueError("案例缺少description(input)")
		criteria=item["semantic_review"].get("criteria")
		if not isinstance(criteria,list) or not criteria or any(not isinstance(value,str) or not value.strip() for value in criteria):
			raise ValueError("案例缺少review_criteria(criteria)")
		response=item.get("response")
		if response is not None:
			if not isinstance(response,dict):
				raise ValueError("response必须是对象或null")
			report=response.get("report")
			if report is not None and (not isinstance(report,dict) or not isinstance(report.get("root_cause"),dict)
				or not isinstance(report["root_cause"].get("text"),str)):
				raise ValueError("模型报告缺少root_cause.text")
			if report is not None:
				claims=report.get("recommendations",[])
				if not isinstance(claims,list) or any(not isinstance(claim,dict) or not isinstance(claim.get("text"),str)
					or not isinstance(claim.get("evidence_ids",[]),list)
					or any(not isinstance(value,str) for value in claim.get("evidence_ids",[])) for claim in claims):
					raise ValueError("排查建议必须包含text和字符串证据ID数组")
		seen.add(case_id)
	return payload


def refresh_workflow_status(item:dict)->str:
	review=item["semantic_review"]
	records=review.setdefault("reviews",[])
	independent=[record for record in records if record.get("role")=="independent"]
	if any(record.get("role")=="adjudicator" for record in records):
		status="adjudicated"
	elif not independent:
		status="pending"
	elif len(independent)==1:
		status="single_reviewer"
	elif len({review_signature(record) for record in independent})==1:
		status="consensus"
	else:
		status="disputed"
	review["workflow_status"]="execution_only" if not report_claims(item) else status
	return review["workflow_status"]


def review_signature(record:dict)->str:
	return canonical_hash({"claims":[(item["claim_id"],item["judgement"]) for item in record["claims"]],
		"facts":[(item["fact_id"],item["coverage"]) for item in record["required_facts"]],
		"completeness":record["case_completeness"],"answerability":record["answerability_assessment"]})


def has_disagreement(records:list[dict])->bool:
	independent=[record for record in records if record.get("role")=="independent"]
	return len(independent)>=2 and len({review_signature(record) for record in independent})>1


def validate_review_record(record:dict,item:dict,reviewer:str,role:str)->dict:
	response=item.get("response") or {}
	if not report_claims(item): raise ValueError("无报告案例只能审核执行行为")
	if record.get("case_id")!=item.get("case_id"): raise ValueError("审核case_id不匹配")
	if record.get("run_id")!=response.get("run_id"): raise ValueError("审核run_id与当前结果不匹配")
	batch=record.get("batch_binding")
	if batch!=item["semantic_review"].get("batch_binding"): raise ValueError("审核记录的模型、Prompt或语料绑定不匹配")
	try:
		reviewed_at=datetime.fromisoformat(record.get("reviewed_at",""))
	except (TypeError,ValueError) as error:
		raise ValueError("reviewed_at必须是带时区的ISO时间") from error
	if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None: raise ValueError("reviewed_at必须包含时区")
	claim_map={claim["claim_id"]:claim for claim in report_claims(item)}
	annotations=record.get("claims")
	if not isinstance(annotations,list) or len(annotations)!=len(claim_map): raise ValueError("必须逐条审核所有报告Claim")
	seen=set()
	evidences={evidence.get("evidence_id"):evidence for evidence in response.get("evidences",[])
		if isinstance(evidence.get("evidence_id"),str)}
	visibility=item["semantic_review"].get("model_visibility",{"status":"unknown","evidence_ids":[]})
	visible=set(visibility.get("evidence_ids",[])) if visibility.get("status")=="known" else None
	prepared_claims=[]
	for annotation in annotations:
		if not isinstance(annotation,dict): raise ValueError("Claim审核必须为对象")
		claim_id=annotation.get("claim_id")
		if claim_id not in claim_map or claim_id in seen: raise ValueError("Claim ID不存在或重复")
		seen.add(claim_id)
		claim=claim_map[claim_id]
		if annotation.get("text")!=claim["text"]: raise ValueError("审核Claim文本与报告原文不一致")
		if annotation.get("evidence_ids")!=claim["evidence_ids"]: raise ValueError("审核引用列表与报告Claim不一致")
		if annotation.get("judgement") not in CLAIM_JUDGEMENTS: raise ValueError("Claim判断状态无效")
		reason=annotation.get("reason")
		if not isinstance(reason,str) or not reason.strip(): raise ValueError("每条Claim必须填写判断理由")
		assessments=annotation.get("evidence_assessments")
		if not isinstance(assessments,list) or len(assessments)!=len(claim["evidence_ids"]): raise ValueError("每条引用Evidence都必须标注")
		assessment_map={}
		for assessment in assessments:
			if not isinstance(assessment,dict): raise ValueError("Evidence判断必须为对象")
			identity=assessment.get("evidence_id")
			if identity not in claim["evidence_ids"] or identity in assessment_map: raise ValueError("Evidence身份与Claim引用不匹配")
			if identity not in evidences: raise ValueError("Evidence不属于当前Run")
			if assessment.get("relation") not in EVIDENCE_RELATIONS: raise ValueError("Evidence支持关系无效")
			relationship_reason=assessment.get("reason")
			if not isinstance(relationship_reason,str) or not relationship_reason.strip(): raise ValueError("每条Evidence判断必须填写理由")
			evidence=evidences[identity]
			content=evidence.get("content_snapshot")
			if content is not None and sha256(content.encode("utf-8")).hexdigest()!=evidence.get("content_hash"):
				raise ValueError("Evidence正文哈希与快照不一致")
			assessment_map[identity]={"evidence_id":identity,"relation":assessment["relation"],"reason":relationship_reason,
				"visibility":"unknown" if visible is None else "visible" if identity in visible else "collected_not_visible",
				"model_visible_content_sha256":sha256(visibility.get("content_snapshots",{}).get(identity,"").encode("utf-8")).hexdigest()
					if identity in visibility.get("content_snapshots",{}) else None,
				"source":evidence.get("source"),"source_ref":evidence.get("source_ref"),
				"source_version":evidence.get("source_version"),"content_hash":evidence.get("content_hash")}
		if set(assessment_map)!=set(claim["evidence_ids"]): raise ValueError("Evidence判断未覆盖全部引用")
		prepared_claims.append({"claim_id":claim_id,"text":claim["text"],"evidence_ids":list(claim["evidence_ids"]),
			"judgement":annotation["judgement"],"reason":reason.strip(),"evidence_assessments":list(assessment_map.values())})
	standard=item["semantic_review"].get("reference_standard")
	if not isinstance(standard,dict): raise ValueError("当前案例缺少冻结的参考标准")
	facts=record.get("required_facts")
	required={fact["fact_id"] for fact in standard["required_facts"]}
	if not isinstance(facts,list) or len(facts)!=len(required): raise ValueError("必须逐项审核所有必需事实")
	prepared_facts=[]
	seen_facts=set()
	for fact in facts:
		if not isinstance(fact,dict) or fact.get("fact_id") not in required or fact["fact_id"] in seen_facts:
			raise ValueError("必需事实ID不存在或重复")
		seen_facts.add(fact["fact_id"])
		if fact.get("coverage") not in FACT_COVERAGE: raise ValueError("必需事实覆盖状态无效")
		if not isinstance(fact.get("reason"),str) or not fact["reason"].strip(): raise ValueError("必需事实判断必须填写理由")
		prepared_facts.append({"fact_id":fact["fact_id"],"coverage":fact["coverage"],"reason":fact["reason"].strip()})
	if seen_facts!=required: raise ValueError("必需事实审核不完整")
	if record.get("case_completeness") not in CASE_COMPLETENESS: raise ValueError("案例完整性判断无效")
	if record.get("answerability_assessment") not in ANSWERABILITY: raise ValueError("证据充分性判断无效")
	case_reason=record.get("case_reason")
	if not isinstance(case_reason,str) or not case_reason.strip(): raise ValueError("案例级判断必须填写理由")
	return {"case_id":item["case_id"],"run_id":response["run_id"],"claims":prepared_claims,
		"required_facts":prepared_facts,"case_completeness":record["case_completeness"],
		"answerability_assessment":record["answerability_assessment"],"case_reason":case_reason.strip(),
		"batch_binding":batch,
		"reviewed_at":reviewed_at.astimezone(timezone.utc).isoformat()}


def summarize_semantic_reviews(results:list[dict])->dict:
	report_cases=[item for item in results if report_claims(item)]
	selected=[]
	claim_counts={name:0 for name in sorted(CLAIM_JUDGEMENTS)}
	root_labels=[]
	recommendation_labels=[]
	fact_statuses=[]
	abstention_results=[]
	claim_pairs=0
	claim_agreements=0
	disagreements={}
	fact_pairs=0
	fact_agreements=0
	fact_disagreements={}
	case_pairs=0
	case_agreements=0
	answerability_pairs=0
	answerability_agreements=0
	completeness_counts={value:0 for value in sorted(CASE_COMPLETENESS)}
	answerability_counts={value:0 for value in sorted(ANSWERABILITY)}
	for item in results:
		workflow=refresh_workflow_status(item) if "semantic_review" in item else "execution_only"
		reviews=item.get("semantic_review",{}).get("reviews",[])
		independent=[entry for entry in reviews if entry.get("role")=="independent"]
		if len(independent)>=2:
			for first,second in combinations(independent,2):
				first_claims={claim["claim_id"]:claim["judgement"] for claim in first["claims"]}
				second_claims={claim["claim_id"]:claim["judgement"] for claim in second["claims"]}
				for identity in first_claims.keys()&second_claims.keys():
					claim_pairs+=1
					left,right=sorted((first_claims[identity],second_claims[identity]))
					if left==right: claim_agreements+=1
					else:
						key=left+"|"+right
						disagreements[key]=disagreements.get(key,0)+1
				first_facts={fact["fact_id"]:fact["coverage"] for fact in first["required_facts"]}
				second_facts={fact["fact_id"]:fact["coverage"] for fact in second["required_facts"]}
				for identity in first_facts.keys()&second_facts.keys():
					fact_pairs+=1
					left,right=sorted((first_facts[identity],second_facts[identity]))
					if left==right: fact_agreements+=1
					else:
						key=left+"|"+right
						fact_disagreements[key]=fact_disagreements.get(key,0)+1
				case_pairs+=1
				case_agreements+=first["case_completeness"]==second["case_completeness"]
				answerability_pairs+=1
				answerability_agreements+=first["answerability_assessment"]==second["answerability_assessment"]
		selected_record=None
		adjudicator=next((entry for entry in reviews if entry.get("role")=="adjudicator"),None)
		if adjudicator is not None: selected_record=adjudicator
		elif workflow=="consensus" and independent: selected_record=independent[0]
		elif workflow=="single_reviewer" and independent: selected_record=independent[0]
		if selected_record is None: continue
		selected.append(selected_record)
		completeness_counts[selected_record["case_completeness"]]+=1
		answerability_counts[selected_record["answerability_assessment"]]+=1
		for claim in selected_record["claims"]:
			claim_counts[claim["judgement"]]+=1
			if claim["claim_id"]=="root_cause": root_labels.append(claim["judgement"])
			elif claim["claim_id"].startswith("recommendation_"): recommendation_labels.append(claim["judgement"])
		fact_statuses.extend(fact["coverage"] for fact in selected_record["required_facts"])
		if item["semantic_review"].get("reference_standard",{}).get("expected_action")=="abstain":
			abstention_results.append(selected_record["answerability_assessment"]=="appropriate")
	covered=sum(value=="covered" for value in fact_statuses)
	applicable_facts=sum(value in ("covered","partial","missing") for value in fact_statuses)
	has_independent_reviews=any(any(entry.get("role")=="independent" for entry in item.get("semantic_review",{}).get("reviews",[])) for item in report_cases)
	agreement_status="measured" if claim_pairs else "not_assessed_single_reviewer" if has_independent_reviews else "not_assessed_pending"
	return {"report_eligible_cases":len(report_cases),
		"execution_only_cases":sum(not report_claims(item) for item in results),
		"pending_cases":sum(refresh_workflow_status(item)=="pending" for item in report_cases),
		"single_reviewer_cases":sum(refresh_workflow_status(item)=="single_reviewer" for item in report_cases),
		"disputed_cases":sum(refresh_workflow_status(item)=="disputed" for item in report_cases),
		"consensus_cases":sum(refresh_workflow_status(item)=="consensus" for item in report_cases),
		"adjudicated_cases":sum(refresh_workflow_status(item)=="adjudicated" for item in report_cases),
		"claim_judgement_counts":claim_counts,"case_completeness_counts":completeness_counts,
		"answerability_assessment_counts":answerability_counts,
		"root_cause_support_rate":sum(value=="supported" for value in root_labels)/len(root_labels) if root_labels else None,
		"unsupported_root_cause_rate":sum(value=="unsupported" for value in root_labels)/len(root_labels) if root_labels else None,
		"recommendation_evidence_support_rate":sum(value=="supported" for value in recommendation_labels)/len(recommendation_labels) if recommendation_labels else None,
		"required_fact_coverage_rate":covered/applicable_facts if applicable_facts else None,
		"evidence_insufficient_correct_refusal_rate":sum(abstention_results)/len(abstention_results) if abstention_results else None,
		"inter_rater_agreement":{"status":agreement_status,
			"claim_agreement_rate":claim_agreements/claim_pairs if claim_pairs else None,
			"claim_pairs_compared":claim_pairs,"disagreement_distribution":disagreements,
			"fact_agreement_rate":fact_agreements/fact_pairs if fact_pairs else None,
			"fact_pairs_compared":fact_pairs,"fact_disagreement_distribution":fact_disagreements,
			"case_completeness_agreement_rate":case_agreements/case_pairs if case_pairs else None,
			"answerability_agreement_rate":answerability_agreements/answerability_pairs if answerability_pairs else None,
			"case_pairs_compared":case_pairs}}


def refresh_review_summary(payload:dict)->None:
	payload["summary"]=summarize_results(payload["results"])
	payload["semantic_quality"]=summarize_semantic_reviews(payload["results"])
	batch=payload.get("review_batch")
	if isinstance(batch,dict): payload["semantic_quality"]["reference_coverage_gaps"]=batch.get("reference_coverage_gaps",[])


def review_record_template(item:dict)->dict:
	return {"case_id":item["case_id"],"run_id":(item.get("response") or {}).get("run_id"),
		"batch_binding":item["semantic_review"].get("batch_binding"),"reviewed_at":"",
		"claims":[{"claim_id":claim["claim_id"],"text":claim["text"],
			"evidence_ids":list(claim["evidence_ids"]),"judgement":"","reason":"",
			"evidence_assessments":[{"evidence_id":identity,"relation":"","reason":""} for identity in claim["evidence_ids"]]}
			for claim in report_claims(item)],
		"required_facts":[{"fact_id":fact["fact_id"],"coverage":"","reason":""}
			for fact in item["semantic_review"]["reference_standard"]["required_facts"]],
		"case_completeness":"","answerability_assessment":"","case_reason":""}


def reviewer_case_material(item:dict)->dict:
	visibility=item["semantic_review"].get("model_visibility",{"status":"unknown","evidence_ids":[],"content_snapshots":{}})
	response=item.get("response") or {}
	evidence=[]
	for item_evidence in response.get("evidences",[]):
		identity=item_evidence.get("evidence_id")
		evidence.append({"evidence_id":identity,"source":item_evidence.get("source"),
			"source_ref":item_evidence.get("source_ref"),"source_version":item_evidence.get("source_version"),
			"source_metadata":item_evidence.get("source_metadata"),"content_hash":item_evidence.get("content_hash"),
			"visibility":"unknown" if visibility["status"]!="known" else "visible" if identity in visibility["evidence_ids"] else "collected_not_visible",
			"model_visible_content":visibility.get("content_snapshots",{}).get(identity),
			"collected_content":item_evidence.get("content_snapshot"),"summary":item_evidence.get("summary")})
	return {"case_id":item["case_id"],"run_id":response.get("run_id"),"question":item["input"],
		"reference_standard":item["semantic_review"].get("reference_standard"),
		"claims":report_claims(item),"evidence":evidence}


def write_json_new(path:Path,payload:dict)->None:
	if path.exists(): raise ValueError("输出文件已存在，不能覆盖")
	created=False
	try:
		with path.open("x",encoding="utf-8",newline="\n") as output:
			created=True
			json.dump(payload,output,ensure_ascii=False,indent=2,allow_nan=False)
			output.write("\n")
	except Exception:
		if created and path.exists(): path.unlink()
		raise


def write_review_template(result_path:Path,output_path:Path,reviewer:str,role:str="independent")->dict:
	payload=load_result(result_path)
	batch=payload.get("review_batch")
	if not isinstance(batch,dict): raise ValueError("先冻结评测批次")
	if not isinstance(reviewer,str) or not reviewer.strip() or role not in ("independent","adjudicator"):
		raise ValueError("审核者标识或角色无效")
	reviews=[]
	for item in payload["results"]:
		workflow=refresh_workflow_status(item)
		if not report_claims(item): continue
		existing=item["semantic_review"].get("reviews",[])
		if role=="independent" and (workflow=="execution_only" or any(entry.get("reviewer")==reviewer for entry in existing)):
			continue
		if role=="adjudicator" and (workflow!="disputed" or any(entry.get("role")=="adjudicator" for entry in existing)):
			continue
		reviews.append(review_record_template(item))
	if not reviews: raise ValueError("没有适合该审核者的新案例")
	case_ids={review["case_id"] for review in reviews}
	materials=[reviewer_case_material(item) for item in payload["results"] if item["case_id"] in case_ids]
	result={"schema_version":1,"batch_binding":review_binding(batch),"reviewer":reviewer.strip(),"role":role,
		"reviewer_material":materials,"reviews":reviews}
	write_json_new(output_path,result)
	return result


def save_result(path:Path,payload:dict)->None:
	# 同目录临时文件写完后原子替换，写入失败不能把原JSON截断。
	temporary=None
	try:
		with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,suffix=".tmp",delete=False) as output:
			temporary=Path(output.name)
			json.dump(payload,output,ensure_ascii=False,indent=2)
			output.write("\n")
			output.flush()
			os.fsync(output.fileno())
		os.replace(temporary,path)
	finally:
		if temporary is not None and temporary.exists():
			temporary.unlink()


def display_width(text:str)->int:
	# 中文通常占两个终端列；按len折行会让中文段落超过终端宽度。
	return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ("W","F") else 1 for char in text)


def wrap_text(text:str,width:int)->list[str]:
	lines=[]
	for paragraph in text.expandtabs(4).split("\n"):
		line=""
		columns=0
		# 工具名和时间戳优先整体换行；只有超过整行宽度的长ID才拆分。
		for token in re.findall(r"[A-Za-z0-9_:/+.\-]+|\s+|.",paragraph):
			if display_width(token)<=width and columns+display_width(token)>width and line:
				lines.append(line)
				line=""
				columns=0
			for char in token:
				char_width=display_width(char)
				if columns+char_width>width and line:
					lines.append(line)
					line=""
					columns=0
				line+=char
				columns+=char_width
		lines.append(line)
	return lines


def render_case(item:dict,index:int,total:int,width:int)->list[str]:
	width=max(20,width)
	lines=["","─"*width,f"案例 {index:02d}/{total:02d}：{item['case_id']}","─"*width]
	def section(title:str,text:str)->None:
		lines.extend(["",title])
		lines.extend("  "+line for line in wrap_text(text,width-2))
	section("【诊断请求 / description】",item["input"])
	response=item.get("response") or {}
	report=response.get("report")
	section("【模型根因】",report["root_cause"]["text"] if report else "（无报告）")
	if report:
		lines.extend(["","【排查建议】"])
		for number,claim in enumerate(report.get("recommendations",[]),1):
			lines.extend("  "+line for line in wrap_text(f"{number}. {claim['text']}",width-2))
			lines.append("    引用证据：")
			for evidence_id in claim.get("evidence_ids",[]):
				lines.extend("    "+line for line in wrap_text(evidence_id,width-4))
			lines.append("")
		section("【证据局限 / limitations】",str(report.get("limitations","")))
	else:
		error=response.get("error_detail") or {}
		section("【执行状态与错误】",f"状态：{response.get('status','无响应')}\n"
			f"错误码：{error.get('code',response.get('error_code')) or item.get('execution_error') or '无'}\n"
			f"错误说明：{error.get('message','无')}")
	section("【规则检查】","通过" if item["rule_passed"] else "未通过")
	failed=[check["name"] for check in item.get("checks",[]) if not check["passed"]]
	if failed:
		lines.extend("  "+line for line in wrap_text("未通过项："+", ".join(failed),width-2))
	lines.extend(["","【审核标准 / review_criteria】"])
	for number,criterion in enumerate(item["semantic_review"]["criteria"],1):
		lines.extend("  "+line for line in wrap_text(f"{number}. {criterion}",width-2))
	lines.append("")
	return lines


def render_semantic_case(item:dict,index:int,total:int,width:int,adjudicate:bool=False)->list[str]:
	width=max(30,width)
	response=item.get("response") or {}
	semantic=item["semantic_review"]
	standard=semantic["reference_standard"]
	visibility=semantic["model_visibility"]
	evidence_by_id={evidence["evidence_id"]:evidence for evidence in response.get("evidences",[])}
	lines=["","="*width,f"案例 {index:02d}/{total:02d}：{item['case_id']}","="*width]
	def section(title:str,text:str)->None:
		lines.extend(["",title])
		lines.extend("  "+line for line in wrap_text(text,width-2))
	section("【用户问题】",item["input"])
	section("【案例参考标准】",f"场景：{standard['scenario']}\n预期行为：{EXPECTED_ACTION_LABELS[standard['expected_action']]}")
	for title,key in (("必须覆盖的事实","required_facts"),("可接受的结论或假设","acceptable_conclusions"),
		("禁止的推断","prohibited_inferences")):
		lines.extend(["",f"【{title}】"])
		values=standard[key]
		for number,value in enumerate(values,1):
			text=value["text"] if isinstance(value,dict) else value
			lines.extend("  "+line for line in wrap_text(f"{number}. {text}",width-2))
	claims=report_claims(item)
	cited_ids={identity for claim in claims for identity in claim["evidence_ids"]}
	for claim in claims:
		lines.extend(["",f"【{claim['claim_id']}】"])
		lines.extend("  "+line for line in wrap_text(claim["text"],width-2))
		if not claim["evidence_ids"]:
			lines.append("  引用：无")
		for identity in claim["evidence_ids"]:
			evidence=evidence_by_id[identity]
			state="模型可见" if visibility["status"]=="known" and identity in visibility["evidence_ids"] else (
				"已收集但模型请求中不可见" if visibility["status"]=="known" else "模型可见范围未知")
			lines.extend(["  "+line for line in wrap_text(f"Evidence {identity} | {state}",width-2)])
			metadata=evidence.get("source_metadata") or {}
			source_info=f"类型={evidence.get('source')}；来源={evidence.get('source_ref')}；版本={evidence.get('source_version') or '未知'}；哈希={evidence.get('content_hash')}"
			if metadata.get("document_id"):
				source_info+=f"；知识文档={metadata['document_id']}；片段={metadata.get('chunk_id','未知')}；检索方法={metadata.get('retrieval_method','未知')}"
			lines.extend("    "+line for line in wrap_text(source_info,width-4))
			model_content=visibility.get("content_snapshots",{}).get(identity) if visibility["status"]=="known" else None
			if model_content is not None:
				lines.extend("    "+line for line in wrap_text("模型实际收到："+str(model_content),width-4))
				full_content=evidence.get("content_snapshot")
				if full_content is not None and model_content!=full_content:
					lines.extend("    "+line for line in wrap_text("Evidence完整正文："+str(full_content),width-4))
				elif full_content is None:
					lines.extend("    "+line for line in wrap_text("Evidence存档摘要："+str(evidence.get("summary") or "（无摘要）"),width-4))
			else:
				content=evidence.get("content_snapshot") or evidence.get("summary") or "（无正文快照）"
				label="收集正文（模型实际内容未捕获）：" if visibility["status"]!="known" else "收集正文（该Evidence未进入模型请求）："
				lines.extend("    "+line for line in wrap_text(label+str(content),width-4))
	unreferenced=[evidence for evidence in response.get("evidences",[]) if evidence.get("evidence_id") not in cited_ids]
	if unreferenced:
		lines.extend(["","【本Run其他已收集Evidence】"])
		for evidence in unreferenced:
			identity=evidence["evidence_id"]
			state="模型可见" if visibility["status"]=="known" and identity in visibility["evidence_ids"] else (
				"已收集但模型请求中不可见" if visibility["status"]=="known" else "模型可见范围未知")
			lines.extend("  "+line for line in wrap_text(f"{identity} | {state} | {evidence.get('source')} | {evidence.get('source_ref')}",width-2))
			model_content=visibility.get("content_snapshots",{}).get(identity) if visibility["status"]=="known" else None
			content=model_content if model_content is not None else evidence.get("content_snapshot") or evidence.get("summary") or "（无正文快照）"
			label="模型实际收到：" if model_content is not None else "收集正文："
			lines.extend("    "+line for line in wrap_text(label+str(content),width-4))
	if adjudicate:
		for existing in semantic.get("reviews",[]):
			if existing.get("role")!="independent": continue
			lines.extend(["",f"【独立评审 {existing['reviewer']}】"])
			for claim in existing["claims"]:
				lines.extend("  "+line for line in wrap_text(f"{claim['claim_id']}：{claim['judgement']}；{claim['reason']}",width-2))
	lines.extend(["",f"模型可见证据范围：{'已按实际请求记录' if visibility['status']=='known' else '未随历史结果保存，未知'}"])
	return lines


def ask_choice(read:Callable,write:Callable,prompt:str,choices:dict[str,str])->str:
	while True:
		answer=read(prompt).strip().lower()
		if answer in choices: return choices[answer]
		if answer in choices.values(): return answer
		write("无效选项，可用："+"、".join(choices))


def review_claims_result(payload:dict,path:Path,read:Callable,write:Callable,reviewer:str|None,role:str,expected_hash:str)->dict:
	if not isinstance(payload.get("review_batch"),dict): raise ValueError("先冻结评测批次")
	if not any(report_claims(item) for item in payload["results"]):
		write("当前批次没有可做语义审核的报告Run；无报告Run仅计入执行评测。")
		refresh_review_summary(payload)
		save_result(path,payload)
		return payload
	if reviewer is None: reviewer=read("审核者标识：").strip()
	if not isinstance(reviewer,str) or not reviewer.strip() or role not in ("independent","adjudicator"):
		raise ValueError("审核者标识或角色无效")
	reviewer=reviewer.strip()
	batch=payload["review_batch"]
	width=min(100,shutil.get_terminal_size(fallback=(100,24)).columns)
	candidates=[]
	for item in payload["results"]:
		status=refresh_workflow_status(item)
		records=item["semantic_review"].get("reviews",[])
		if role=="independent" and report_claims(item) and not any(record.get("reviewer")==reviewer for record in records):
			candidates.append(item)
		if role=="adjudicator" and status=="disputed" and not any(record.get("role")=="adjudicator" for record in records):
			candidates.append(item)
	if not candidates:
		write("当前审核者没有待处理的可评审案例。")
		refresh_review_summary(payload)
		if file_hash(path)!=expected_hash: raise ValueError("批次结果已被其他审核更新，请重新加载")
		save_result(path,payload)
		return payload
	for index,item in enumerate(candidates,1):
		for line in render_semantic_case(item,index,len(candidates),width,role=="adjudicator"):
			write(line)
		claims=[]
		for claim in report_claims(item):
			judgement=ask_choice(read,write,"判断[ s 支持 / p 部分支持 / u 不支持 / c 证据冲突 / i 无法判断 ]：",
				{"s":"supported","p":"partially_supported","u":"unsupported","c":"evidence_conflict","i":"indeterminate"})
			reason=read("Claim判断理由：").strip()
			while not reason:
				write("理由不能为空。")
				reason=read("Claim判断理由：").strip()
			assessments=[]
			for identity in claim["evidence_ids"]:
				relation=ask_choice(read,write,f"Evidence {identity} 与该Claim的关系 [s 支持 / c 反驳 / x 背景 / n 无关 ]：",
					{"s":"supports","c":"contradicts","x":"context_only","n":"not_relevant"})
				evidence_reason=read("Evidence判断理由：").strip()
				while not evidence_reason:
					write("理由不能为空。")
					evidence_reason=read("Evidence判断理由：").strip()
				assessments.append({"evidence_id":identity,"relation":relation,"reason":evidence_reason})
			claims.append({"claim_id":claim["claim_id"],"text":claim["text"],"evidence_ids":claim["evidence_ids"],
				"judgement":judgement,"reason":reason,"evidence_assessments":assessments})
		facts=[]
		for fact in item["semantic_review"]["reference_standard"]["required_facts"]:
			coverage=ask_choice(read,write,f"必需事实 {fact['fact_id']} [c 覆盖 / p 部分 / m 缺失 / n 不适用 ]：",
				{"c":"covered","p":"partial","m":"missing","n":"not_applicable"})
			fact_reason=read("覆盖判断理由：").strip()
			while not fact_reason:
				write("理由不能为空。")
				fact_reason=read("覆盖判断理由：").strip()
			facts.append({"fact_id":fact["fact_id"],"coverage":coverage,"reason":fact_reason})
		completeness=ask_choice(read,write,"报告完整性 [c 完整 / p 部分完整 / i 不完整 ]：",
			{"c":"complete","p":"partially_complete","i":"incomplete"})
		answerability=ask_choice(read,write,"回答行为 [a 符合预期 / o 应拒答而作答 / u 可答却拒答 / i 无法判断 ]：",
			{"a":"appropriate","o":"overclaim","u":"unnecessary_abstention","i":"indeterminate"})
		case_reason=read("案例整体理由：").strip()
		while not case_reason:
			write("理由不能为空。")
			case_reason=read("案例整体理由：").strip()
		record={"case_id":item["case_id"],"run_id":(item.get("response") or {}).get("run_id"),
			"batch_binding":case_review_binding(batch,item),"reviewed_at":datetime.now(timezone.utc).isoformat(),
			"claims":claims,"required_facts":facts,
			"case_completeness":completeness,"answerability_assessment":answerability,"case_reason":case_reason}
		validated=validate_review_record(record,item,reviewer,role)
		existing=item["semantic_review"].get("reviews",[])
		if role=="adjudicator" and (not has_disagreement(existing) or any(entry.get("role")=="adjudicator" for entry in existing)):
			raise ValueError("仅未解决的双人分歧可以进入一次仲裁")
		if file_hash(path)!=expected_hash: raise ValueError("批次结果已被其他审核更新，请重新加载")
		item["semantic_review"].setdefault("reviews",[]).append({"reviewer":reviewer,"role":role,
			"reviewed_at":validated.pop("reviewed_at"),"batch_binding":review_binding(batch),**validated})
		refresh_review_summary(payload)
		save_result(path,payload)
		expected_hash=file_hash(path)
	return payload


def review_result(path:Path,read:Callable=input,write:Callable=print,reviewer:str|None=None,role:str="independent")->dict:
	original_hash=file_hash(path)
	payload=load_result(path)
	if not isinstance(payload.get("review_batch"),dict): raise ValueError("先运行review-freeze冻结批次，再按Claim审核")
	return review_claims_result(payload,path,read,write,reviewer,role,original_hash)
