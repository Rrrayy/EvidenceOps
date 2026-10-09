import json
from dataclasses import dataclass
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
		case=EvalCase(**{**item,"tool_calls":tuple(item["tool_calls"]),
			"required_sources":tuple(item["required_sources"]),"review_criteria":tuple(item["review_criteria"]),
			"evidence_checks":tuple(item.get("evidence_checks",[]))})
		if not isinstance(case.case_id,str) or not case.case_id.strip() or case.case_id in seen:
			raise ValueError("case_id不能为空或重复")
		if not isinstance(case.description,str) or not case.description.strip():
			raise ValueError("description不能为空")
		if case.expected_status not in ("succeeded","failed"):
			raise ValueError("评测案例必须声明成功或失败终态")
		if (case.expected_status=="failed")!=(isinstance(case.expected_error_code,str) and bool(case.expected_error_code.strip())):
			raise ValueError("失败案例必须声明错误码，成功案例错误码必须为空")
		if case.expected_status=="succeeded" and case.expected_error_code is not None:
			raise ValueError("成功案例不能声明错误码")
		for call in case.tool_calls:
			if not isinstance(call,dict) or not isinstance(call.get("tool_name"),str) or not isinstance(call.get("arguments"),dict):
				raise ValueError("tool_calls必须包含工具名和参数对象")
		if not 1<=len(case.tool_calls)<=16:
			raise ValueError("案例必须包含1到16个预期工具调用")
		if any(value not in ("log","metric","config") for value in case.required_sources):
			raise ValueError("未知证据来源")
		if not case.review_criteria or any(not isinstance(value,str) or not value.strip() for value in case.review_criteria):
			raise ValueError("案例必须包含人工审核标准")
		if not isinstance(case.fixture_hashes,dict) or not case.fixture_hashes:
			raise ValueError("案例必须绑定样本指纹")
		if case.expected_failure_stage not in ("tool","collection"):
			raise ValueError("未知预期失败阶段")
		if case.expected_error_detail_code is not None and (not isinstance(case.expected_error_detail_code,str)
			or not case.expected_error_detail_code.strip() or case.expected_status!="failed"):
			raise ValueError("内层错误码只能在失败案例声明")
		for expected in case.evidence_checks:
			if not isinstance(expected,dict) or expected.get("source") not in ("log","metric","config"):
				raise ValueError("证据检查必须声明有效source")
			fragments=expected.get("summary_contains")
			if not isinstance(fragments,list) or not fragments or any(not isinstance(value,str) or not value for value in fragments):
				raise ValueError("证据检查必须包含非空摘要片段")
		seen.add(case.case_id)
		cases.append(case)
	return tuple(cases)


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
	check("record_ownership",all(item.run_id==result.run.run_id for item in result.execution_records))
	check("records_present",bool(result.execution_records))
	check("tool_allowlist",all(item.tool_name in {call["tool_name"] for call in case.tool_calls}
		for item in result.execution_records if item.kind=="tool"))
	if case.expected_status=="succeeded":
		check("tool_success",all(item.status=="succeeded" for item in result.execution_records if item.kind=="tool"))
	elif case.expected_failure_stage=="tool":
		check("failed_tool_record",any(item.kind=="tool" and item.status=="failed"
			and item.error_code==case.expected_error_code for item in result.execution_records))
	else:
		# 空指标在Collector失败，不能错误要求成功的查询工具记录为failed。
		tool_records=[item for item in result.execution_records if item.kind=="tool"]
		check("collection_after_tool_success",bool(tool_records) and all(item.status=="succeeded" for item in tool_records))
	for index,expected in enumerate(case.tool_calls):
		# 同名工具允许多次调用；参数类型也要匹配，避免 True 冒充整数 1。
		matching=[item.query_arguments for item in result.execution_records if item.kind=="tool" and item.tool_name==expected["tool_name"]]
		if observed_calls is not None:
			matching=[item["arguments"] for item in observed_calls if item["tool_name"]==expected["tool_name"]]
		check(f"tool_parameters_{index}",any(
			item is not None and all(
				type(item.get(key)) is type(value) and item.get(key)==value
				for key,value in expected["arguments"].items()
			) for item in matching
		))
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
	return checks


def summarize_results(results:list[dict])->dict:
	# pending 仍留在总分母中，避免只审核容易案例就抬高通过率。
	if not isinstance(results,list) or not results:
		raise ValueError("评测结果不能为空")
	for item in results:
		if not isinstance(item,dict) or type(item.get("rule_passed")) is not bool:
			raise ValueError("案例必须包含布尔类型的rule_passed")
		review=item.get("semantic_review")
		if not isinstance(review,dict) or review.get("status") not in ("pending","passed","failed"):
			raise ValueError("人工审核状态无效")
	count=len(results)
	rule_count=sum(item["rule_passed"] for item in results)
	semantic_count=sum(item["semantic_review"]["status"]=="passed" for item in results)
	final_count=sum(item["rule_passed"] and item["semantic_review"]["status"]=="passed" for item in results)
	return {
		"case_count":count,"rule_passed_count":rule_count,"rule_pass_rate":rule_count/count,
		"semantic_passed_count":semantic_count,"semantic_pass_rate":semantic_count/count,
		"final_passed_count":final_count,"final_pass_rate":final_count/count,
		"execution_error_count":sum(item.get("execution_error") is not None for item in results),
		"semantic_review_pending":sum(item["semantic_review"]["status"]=="pending" for item in results),
	}


def run_suite(cases:tuple[EvalCase,...],factory:Callable,mode:str)->dict:
	# 每个案例独立创建资源，避免 Mock 游标和运行状态污染后续案例。
	if not cases or mode not in ("mock","real"):
		raise ValueError("需要非空案例及mock/real模式")
	results=[]
	batch_id=f"eval-{uuid4()}"
	for case in cases:
		started=perf_counter()
		checks=[]
		response=None
		error=None
		try:
			with factory(case) as service:
				execution=service.execute(f"{batch_id}-{case.case_id}",case.description)
				checks=check_execution(case,execution,getattr(service,"observed_calls",None))
				response=to_response(execution)
		except Exception as exception:
			# 不输出原始异常以免泄露凭据；异常案例仍保留在通过率分母中。
			error=type(exception).__name__
		# 规则通过不等于语义正确；审核保留 pending，未知 usage 不填零。
		results.append({
			"case_id":case.case_id,"checks":checks,"execution_error":error,
			"input":case.description,"fixture_hashes":case.fixture_hashes,
			"rule_passed":error is None and bool(checks) and all(item["passed"] for item in checks),
			"wall_duration_ms":(perf_counter()-started)*1000,
			"semantic_review":{"status":"pending","criteria":list(case.review_criteria)},
			"token_usage":None,"cost":None,"response":response,
		})
	return {
		"schema_version":1,"batch_id":batch_id,"mode":mode,
		"summary":summarize_results(results),
		"results":results,
	}
