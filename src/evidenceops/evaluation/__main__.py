import argparse
import json
import os
import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Lock

from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ModelRequest,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.connectors.local_config import build_local_config_tool
from evidenceops.connectors.local_log import build_local_log_tool
from evidenceops.connectors.local_metric import build_local_metric_tool
from evidenceops.evaluation.core import EvalCase,load_cases,run_suite
from evidenceops.evaluation.review import review_result,save_result
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.infrastructure.providers.openai_compatible_provider import OpenAICompatibleProvider


PROJECT_ROOT=Path(__file__).resolve().parents[3]


class EvaluationService:
	def __init__(self,service,calls:list[dict],lock:Lock)->None:
		self._service=service
		self._calls=calls
		self._lock=lock

	@property
	def observed_calls(self)->tuple[dict,...]:
		with self._lock:
			return tuple(deepcopy(self._calls))

	def execute(self,request_id:str,description:str):
		return self._service.execute(request_id,description)


def mock_answer(request:ModelRequest)->StructuredFinalAnswer:
	# 从真实工具观察中取 ID，不预填证据；Mock 只证明工程链路。
	ids=[]
	facts=[]
	for message in request.messages:
		if message.get("role")=="tool":
			observation=json.loads(message["content"])
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
	calls_seen=[]
	calls_lock=Lock()
	observed_tools=[]
	for spec in tools:
		# Eval捕获校验前的实际参数，不扩展线上执行记录中的敏感字段白名单。
		def validate(arguments,spec=spec):
			with calls_lock:
				calls_seen.append({"tool_name":spec.name,"arguments":deepcopy(arguments)})
			return spec.validate_arguments(arguments)
		observed_tools.append(replace(spec,validate_arguments=validate))
	tools=tuple(observed_tools)
	if mode=="mock":
		calls=tuple(ToolCall(f"eval-call-{index}",item["tool_name"],item["arguments"]) for index,item in enumerate(case.tool_calls))
		provider=MockProvider((ToolCallBatch(calls),mock_answer))
		model="eval-mock"
	else:
		model=os.environ["EVIDENCEOPS_MODEL_NAME"]
		provider=OpenAICompatibleProvider(os.environ["EVIDENCEOPS_MODEL_BASE_URL"],os.environ["EVIDENCEOPS_MODEL_API_KEY"])
	assembly=None
	try:
		assembly=build_agent_diagnosis_assembly(provider,mode,tools,"order-service",model=model,model_timeout_seconds=60,max_steps=5)
		yield EvaluationService(assembly.diagnosis_service,calls_seen,calls_lock)
	finally:
		# 构造失败也要释放 Provider，组装成功时由 assembly 统一关闭。
		if assembly is not None:
			assembly.close()
		else:
			close=getattr(provider,"close",None)
			if callable(close):
				close()


def main(argv:list[str]|None=None)->int:
	arguments=list(sys.argv[1:] if argv is None else argv)
	if arguments and arguments[0]=="review":
		parser=argparse.ArgumentParser(description="人工审核Eval结果，不调用模型")
		parser.add_argument("result",type=Path,help="eval_result.json文件路径")
		args=parser.parse_args(arguments[1:])
		try:
			review_result(args.result)
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
	args=parser.parse_args(arguments)
	if args.mode=="real":
		missing=[name for name in ("EVIDENCEOPS_MODEL_BASE_URL","EVIDENCEOPS_MODEL_API_KEY","EVIDENCEOPS_MODEL_NAME") if not os.getenv(name," ").strip()]
		if missing:
			parser.error("缺少配置："+",".join(missing))
	cases=load_cases(args.cases)
	report=run_suite(cases,lambda case:case_service(case,args.mode),args.mode)
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
