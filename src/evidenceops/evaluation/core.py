import json
from decimal import Decimal,InvalidOperation
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
			if not isinstance(dependencies,list) or any(type(value) is not int or value<0 or value>=index for value in dependencies) or len(set(dependencies))!=len(dependencies):
				raise ValueError("depends_on必须引用不重复的前置调用下标")
		if not 0<=len(case.tool_calls)<=16:
			raise ValueError("案例最多包含16个预期工具调用")
		if any(value not in ("log","metric","config") for value in case.required_sources):
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
			if not isinstance(expected,dict) or expected.get("source") not in ("log","metric","config"):
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


def match_calls(expected:tuple[dict,...],actual:tuple[dict,...])->bool:
	# 匹配使用增广路径，避免宽泛预期抢占只能匹配特定预期的调用。
	matched={}
	def assign(index:int,visited:set[int])->bool:
		call=expected[index]
		for position,item in enumerate(actual):
			if position in visited or item.get("tool_name")!=call["tool_name"]:
				continue
			arguments=item.get("arguments")
			if call.get("strict_arguments",False) and isinstance(arguments,dict) and set(arguments)!=set(call["arguments"]):
				continue
			if not isinstance(arguments,dict) or not all(
				key in arguments and matching_value(value,arguments[key])
				for key,value in call["arguments"].items()
			):
				continue
			visited.add(position)
			if position not in matched or assign(matched[position],visited):
				matched[position]=index
				return True
		return False
	return len(expected)==len(actual) and all(assign(index,set()) for index in range(len(expected)))


def match_dependencies(expected:tuple[dict,...],actual:tuple[dict,...])->bool:
	if len(expected)!=len(actual):
		return False
	assigned={}
	def assign(index:int,used:set[int])->bool:
		if index==len(expected):
			return True
		call=expected[index]
		for position,item in enumerate(actual):
			if position in used or not match_calls((call,),(item,)):
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
		check(f"tool_parameters_{index}",any(
			item is not None and all(
				key in item and matching_value(value,item[key])
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


def run_suite(cases:tuple[EvalCase,...],factory:Callable,mode:str,pricing:dict|None=None)->dict:
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
		error=None
		try:
			with factory(case) as service:
				execution=service.execute(f"{batch_id}-{case.case_id}",case.description)
				checks=check_execution(case,execution,getattr(service,"observed_calls",None))
				response=to_response(execution)
				usage=summarize_usage(execution.execution_records)
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
			"token_usage":usage,"cost":calculate_cost(usage,pricing) if pricing is not None and response is not None
				and (execution.model_config or {}).get("model_id")==pricing.get("model") else None,"response":response,
		})
	return {
		"schema_version":1,"batch_id":batch_id,"mode":mode,
		"summary":summarize_results(results),
		"results":results,
	}
