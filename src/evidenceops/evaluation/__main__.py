import argparse
import json
import os
import sys
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import inspect
import subprocess
from pathlib import Path
from threading import Lock

from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ModelRequest,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.token_budget import ContextConfig
from evidenceops.connectors.local_config import build_local_config_tool
from evidenceops.connectors.local_log import build_local_log_tool
from evidenceops.connectors.local_metric import build_local_metric_tool
from evidenceops.evaluation.core import EvalCase,attach_retrieval_comparison,load_cases,run_suite
from evidenceops.evaluation.review import (attach_review_batch_metadata,freeze_review_batch,import_reviews,
	load_reference_standards,review_result,save_result,write_review_template)
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.infrastructure.providers.openai_compatible_provider import OpenAICompatibleProvider


PROJECT_ROOT=Path(__file__).resolve().parents[3]


class EvaluationService:
	def __init__(self,service,calls:list[dict],requests:list[dict],lock:Lock)->None:
		self._service=service
		self._calls=calls
		self._requests=requests
		self._lock=lock

	@property
	def observed_calls(self)->tuple[dict,...]:
		with self._lock:
			return tuple(deepcopy(self._calls))

	@property
	def observed_model_requests(self)->tuple[dict,...]:
		with self._lock:
			return tuple(deepcopy(self._requests))

	def execute(self,request_id:str,description:str):
		return self._service.execute(request_id,description)


class RecordingProvider:
	def __init__(self,provider,requests:list[dict],lock:Lock)->None:
		self._provider=provider
		self._requests=requests
		self._lock=lock

	def complete(self,request:ModelRequest):
		payload={"request_id":request.request_id,"run_id":request.run_id,"model":request.model,
			"response_format":request.response_format,"max_output_tokens":request.max_output_tokens,
			"context_window_tokens":request.context_window_tokens,"estimated_input_tokens":request.estimated_input_tokens,
			"messages":deepcopy(request.messages),"tools":deepcopy(request.tools)}
		canonical=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
		record={**payload,"request_payload_sha256":sha256(canonical.encode("utf-8")).hexdigest(),
			"evidence_id_mentions":tuple(extract_evidence_id_mentions(request.messages)),"provider_status":"pending"}
		with self._lock:
			self._requests.append(record)
		try:
			response=self._provider.complete(request)
		except Exception:
			record["provider_status"]="failed"
			raise
		record["provider_status"]="completed"
		return response

	def close(self)->None:
		close=getattr(self._provider,"close",None)
		if callable(close): close()


def extract_evidence_id_mentions(messages:tuple[dict,...])->list[str]:
	identities=[]
	def collect(value):
		if isinstance(value,dict):
			identity=value.get("evidence_id")
			if isinstance(identity,str) and identity not in identities: identities.append(identity)
			for child in value.values(): collect(child)
		elif isinstance(value,list):
			for child in value: collect(child)
	for message in messages:
		content=message.get("content")
		if not isinstance(content,str): continue
		try: collect(json.loads(content))
		except (ValueError,TypeError): continue
	return identities


def mock_answer(request:ModelRequest)->StructuredFinalAnswer:
	# 从真实工具观察中取 ID，不预填证据；Mock 只证明工程链路。
	ids=[]
	facts=[]
	for message in request.messages:
		if message.get("role")=="tool":
			observation=json.loads(message["content"])
			if observation.get("ok") and observation.get("evidence_id") is None and "matches" in (observation.get("data") or {}):
				matches=observation.get("data",{}).get("matches",[])
				ids.extend(item["evidence_id"] for item in matches if item.get("evidence_id"))
				facts.append("知识资料仅供排查参考，不能证明现场根因" if matches else "未检索到知识资料")
			if observation.get("ok") and observation.get("evidence_id"):
				ids.append(observation["evidence_id"])
				data=observation["data"]
				if "matches" in data:
					facts.append(f"日志匹配{data['total_count']}条，返回{data['returned_count']}条；"
						f"{'已截断，不能代表全部记录' if data['truncated'] else '未截断'}")
					if data["total_count"]==0:
						facts.append("本次条件无匹配，不代表服务没有故障")
				elif "samples" in data:
					facts.append(f"指标匹配{data['total_count']}条，返回{data['returned_count']}条；"
						f"{'已截断，不能判断完整趋势' if data['truncated'] else '未截断'}")
					for sample in data["samples"]:
						record=sample["record"]
						facts.append(f"{record['timestamp']}线程活跃{record['active_threads']}/{record['thread_limit']}，"
							f"排队{record['pending_tasks']}")
				elif "config" in data:
					record=data["config"]["record"]
					facts.append(f"{data['at_time']}生效版本{record['config_version']}，"
						f"RPC超时{record['rpc_timeout_ms']}毫秒，允许额外重试{record['max_retries']}次；不证明实际重试")
	return StructuredFinalAnswer({
		"root_cause":{"text":"；".join(facts)+"。以上为工具观测，不能确定因果或唯一根因。","evidence_ids":ids},
		"recommendations":[{"text":"补查下游耗时、调用链和实际重试记录","evidence_ids":ids}],
		"confidence":0.5,"limitations":"Mock模板仅用于工程验证；缺少下游、trace、实际重试数据；"
			"配置快照不能证明整个窗口无变更，异窗口数据不能直接建立同时相关性，截断结果不能推断完整趋势",
	})


def verify_fixtures(case:EvalCase)->None:
	# 样本变化必须重新审核标准，不能沿用旧答案评价新输入。
	for relative_path,expected_hash in case.fixture_hashes.items():
		path=(PROJECT_ROOT/relative_path).resolve()
		if not path.is_relative_to(PROJECT_ROOT/"samples"):
			raise ValueError("评测样本必须位于samples目录")
		if sha256(path.read_bytes()).hexdigest()!=expected_hash:
			raise ValueError("评测样本指纹变化，请重新审核案例")


@contextmanager
def case_service(case:EvalCase,mode:str):
	verify_fixtures(case)
	tools=(build_local_log_tool(),build_local_metric_tool(),build_local_config_tool())
	engine=None
	if any(call["tool_name"]=="search_knowledge" for call in case.tool_calls):
		from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
		from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
		from evidenceops.infrastructure.knowledge_tools import configured_knowledge_tools
		engine=create_database_engine(DatabaseSettings.from_environment())
		try:
			knowledge_tools=configured_knowledge_tools(SqlAlchemyDiagnosisPersistence(create_session_factory(engine)))
			if not knowledge_tools:
				raise ValueError("知识评测需要启用知识检索")
			tools+=knowledge_tools
		except Exception:
			engine.dispose()
			raise
	calls_seen=[]
	model_requests=[]
	calls_lock=Lock()
	if mode=="mock":
		rounds=[]
		for index,item in enumerate(case.tool_calls):
			dependencies=item.get("depends_on",[])
			round_index=max((rounds[dependency] for dependency in dependencies),default=-1)+1
			rounds.append(round_index)
		batches=tuple(ToolCallBatch(tuple(ToolCall(f"eval-call-{index}",item["tool_name"],item["arguments"])
			for index,item in enumerate(case.tool_calls) if rounds[index]==round_index)) for round_index in range(max(rounds,default=-1)+1))
		provider=MockProvider(batches+(mock_answer,))
		model="eval-mock"
	else:
		model=os.environ["EVIDENCEOPS_MODEL_NAME"]
		provider=OpenAICompatibleProvider(os.environ["EVIDENCEOPS_MODEL_BASE_URL"],os.environ["EVIDENCEOPS_MODEL_API_KEY"])
	provider=RecordingProvider(provider,model_requests,calls_lock)
	assembly=None
	try:
		assembly=build_agent_diagnosis_assembly(provider,mode,tools,"order-service",model=model,model_timeout_seconds=60,max_steps=5,
			model_config={"model_id":model},context_config=ContextConfig() if any(call["tool_name"]=="search_knowledge" for call in case.tool_calls) or case.required_chunk_ids else None)
		execute_tool=assembly.runtime.execute
		def observe_tool(tool_name,arguments,tool_call_id=None,**options):
			# 仅在评测内存中记录完整参数，按调用ID关联运行时执行记录。
			with calls_lock:
				calls_seen.append({"tool_name":tool_name,"arguments":deepcopy(arguments),"tool_call_id":tool_call_id})
			return execute_tool(tool_name,arguments,tool_call_id,**options)
		assembly.runtime.execute=observe_tool
		yield EvaluationService(assembly.diagnosis_service,calls_seen,model_requests,calls_lock)
	finally:
		# 构造失败也要释放 Provider，组装成功时由 assembly 统一关闭。
		if assembly is not None:
			assembly.close()
		else:
			close=getattr(provider,"close",None)
			if callable(close):
				close()
		if engine is not None:
			engine.dispose()


def main(argv:list[str]|None=None)->int:
	arguments=list(sys.argv[1:] if argv is None else argv)
	if arguments and arguments[0]=="review-freeze":
		parser=argparse.ArgumentParser(description="冻结人工语义评测批次与可追溯快照")
		parser.add_argument("result",type=Path)
		parser.add_argument("--cases",type=Path,required=True)
		parser.add_argument("--references",type=Path,required=True)
		parser.add_argument("--output",type=Path,required=True)
		args=parser.parse_args(arguments[1:])
		try:
			freeze_review_batch(args.result,args.cases,args.references,args.output)
		except (OSError,ValueError) as error:
			print(f"冻结失败：{error}",file=sys.stderr)
			return 2
		print(f"人工语义评测批次已冻结：{args.output}")
		return 0
	if arguments and arguments[0]=="review-template":
		parser=argparse.ArgumentParser(description="导出可校验的逐Claim人工审核JSON模板")
		parser.add_argument("result",type=Path)
		parser.add_argument("--reviewer",required=True)
		parser.add_argument("--role",choices=("independent","adjudicator"),default="independent")
		parser.add_argument("--output",type=Path,required=True)
		args=parser.parse_args(arguments[1:])
		try:
			write_review_template(args.result,args.output,args.reviewer,args.role)
		except (OSError,ValueError) as error:
			print(f"审核模板导出失败：{error}",file=sys.stderr)
			return 2
		print(f"审核模板已生成：{args.output}")
		return 0
	if arguments and arguments[0]=="review-import":
		parser=argparse.ArgumentParser(description="导入带证据判断的人工审核记录")
		parser.add_argument("result",type=Path)
		parser.add_argument("reviews",type=Path)
		args=parser.parse_args(arguments[1:])
		try:
			import_reviews(args.result,args.reviews)
		except (OSError,ValueError) as error:
			print(f"审核导入失败：{error}",file=sys.stderr)
			return 2
		return 0
	if arguments and arguments[0]=="review":
		parser=argparse.ArgumentParser(description="人工审核Eval结果，不调用模型")
		parser.add_argument("result",type=Path,help="eval_result.json文件路径")
		parser.add_argument("--reviewer",help="唯一评审者标识")
		parser.add_argument("--role",choices=("independent","adjudicator"),default="independent")
		args=parser.parse_args(arguments[1:])
		try:
			if args.reviewer is None and args.role=="independent": review_result(args.result)
			else: review_result(args.result,reviewer=args.reviewer,role=args.role)
		except (KeyboardInterrupt,EOFError):
			print("\n审核已中断，已完成案例已保存；重运行命令可继续。",file=sys.stderr)
			return 130
		except (OSError,ValueError) as error:
			print(f"审核失败：{error}",file=sys.stderr)
			return 2
		return 0
	parser=argparse.ArgumentParser(description="离线诊断评测：规则检查不代表语义准确率")
	# 默认 Mock，真实模式由用户显式选择，避免无意产生模型 API 费用。
	parser.add_argument("--mode",choices=("mock","real"),default="mock")
	parser.add_argument("--cases",type=Path,default=PROJECT_ROOT/"samples"/"evaluation"/"cases.json")
	parser.add_argument("--output",type=Path,help="直接以UTF-8保存结果，避免PowerShell管道编码转换")
	parser.add_argument("--pricing",type=Path,help="模型价格JSON文件，含model、currency、version和每百万输入/输出Token单价")
	parser.add_argument("--retrieval-comparison",type=Path,help="关联已有同查询和同快照的检索对照结果")
	parser.add_argument("--references",type=Path,default=PROJECT_ROOT/"samples"/"evaluation"/"semantic_references.json")
	args=parser.parse_args(arguments)
	if args.mode=="real":
		missing=[name for name in ("EVIDENCEOPS_MODEL_BASE_URL","EVIDENCEOPS_MODEL_API_KEY","EVIDENCEOPS_MODEL_NAME") if not os.getenv(name," ").strip()]
		if missing:
			parser.error("缺少配置："+",".join(missing))
	cases=load_cases(args.cases)
	references=load_reference_standards(args.references)
	missing_references=[case.case_id for case in cases if case.case_id not in references]
	if missing_references: parser.error("缺少人工参考标准："+",".join(missing_references))
	pricing=json.loads(args.pricing.read_text(encoding="utf-8")) if args.pricing else None
	report=run_suite(cases,lambda case:case_service(case,args.mode),args.mode,pricing,references)
	try:
		prompt_source=inspect.getsource(__import__("evidenceops.application.agent_loop",fromlist=["AgentLoop"]).AgentLoop._build_history)
		prompt_fingerprint=sha256(prompt_source.encode("utf-8")).hexdigest()
	except (OSError,TypeError):
		prompt_fingerprint=None
	try:
		revision=subprocess.run(["git","rev-parse","HEAD"],cwd=PROJECT_ROOT,capture_output=True,text=True,check=True).stdout.strip()
	except (OSError,subprocess.CalledProcessError):
		revision=None
	attach_review_batch_metadata(report,args.cases,args.references,prompt_fingerprint,revision)
	if args.retrieval_comparison:
		attach_retrieval_comparison(report,json.loads(args.retrieval_comparison.read_text(encoding="utf-8-sig")))
	if args.output is not None:
		try:
			save_result(args.output,report)
		except OSError as error:
			print(f"保存失败：{error}",file=sys.stderr)
			return 2
		print(f"评测结果已保存：{args.output}")
		print(json.dumps(report["summary"],ensure_ascii=False,indent=2))
	else:
		print(json.dumps(report,ensure_ascii=False,indent=2))
	return 0 if report["summary"]["rule_pass_rate"]==1 else 1


if __name__=="__main__":
	raise SystemExit(main())
