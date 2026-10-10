import json

from datetime import datetime,timezone
from time import perf_counter
from evidenceops.application.execution_record import ExecutionRecord

from dataclasses import dataclass,replace
from typing import Any
from uuid import uuid4

from evidenceops.application.llm_gateway import LLMGateway,ModelGatewayError
from evidenceops.application.model_protocol import FinalAnswer,ModelRequest,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.tool_runtime import ToolResult,ToolRuntime,ToolSpec
from evidenceops.application.run_events import RunEvents
from evidenceops.application.run_budget import RunBudget,RunBudgetExceeded


@dataclass(frozen=True,slots=True)
class AgentLoopResult:
	final_answer:FinalAnswer|StructuredFinalAnswer|None
	tool_results:tuple[ToolResult,...]
	error_code:str|None
	error_message:str|None=None
	execution_records:tuple[ExecutionRecord,...]=()


class AgentLoop:
	def __init__(
		self,
		gateway:LLMGateway,
		runtime:ToolRuntime,
		tools:tuple[ToolSpec,...]|tuple[dict[str,Any],...]=(),
		model:str="mock-model",
		timeout_seconds:float=10.0,
		max_steps:int=3,
		response_format:str="text",
	)->None:
		if not isinstance(model,str) or not model.strip():
			raise ValueError("model不能为空")

		if timeout_seconds<=0:
			raise ValueError("timeout_seconds必须大于0")

		if max_steps<=0:
			raise ValueError("max_steps必须大于0")

		if response_format not in ("text","json_object"):
			raise ValueError("response_format必须是text或json_object")

		self._gateway=gateway
		self._runtime=runtime
		self._tools=tuple(tool.to_model_schema() if isinstance(tool,ToolSpec) else tool for tool in tools)
		self._model=model
		self._timeout_seconds=timeout_seconds
		self._max_steps=max_steps
		self._response_format=response_format

	def run(self,prompt:str,run_id:str|None=None,events:RunEvents|None=None,budget:RunBudget|None=None)->AgentLoopResult:
		if not isinstance(prompt,str) or not prompt.strip():
			raise ValueError("prompt不能为空")

		if run_id is None:
			run_id=str(uuid4())

		if not isinstance(run_id,str) or not run_id.strip():
			raise ValueError("run_id不能为空")

		if self._response_format=="json_object":
			history:tuple[dict[str,Any],...]=(
				{
					"role":"system",
					"content":(
						"最终回答必须是合法JSON对象，并严格使用以下字段："
						"root_cause、recommendations、confidence、limitations。"
						"root_cause必须包含text和evidence_ids；"
						"recommendations必须是数组，数组项必须包含text和evidence_ids；"
						"confidence必须是0到1之间的数字；"
						"limitations必须是非空字符串；"
						"evidence_ids只能填写工具结果中出现过的Evidence ID。"
						"工具查询必须忠实保留用户指定的服务、环境、日期和时区，不得擅自改写月份或年份。"
						"时间参数使用带时区的ISO 8601字符串，如2026-10-05T10:00:00+08:00；"
						"同一故障窗口的日志与指标使用相同start_time和end_time。"
					),
				},
				{
					"role":"user",
					"content":prompt,
				},
			)
		else:
			history=({"role":"user","content":prompt,},)

		records:list[ExecutionRecord]=[]
		def finish(final_answer,tool_results,error_code,error_message=None):
			return AgentLoopResult(final_answer,tool_results,error_code,error_message,tuple(records))

		tool_results:list[ToolResult]=[]

		# 限制模型轮次，同轮多工具批次不逐项消耗轮次预算。
		for model_round in range(1,self._max_steps+1):
			try:
				call_timeout=budget.limit(self._timeout_seconds) if budget is not None else self._timeout_seconds
			except RunBudgetExceeded:
				return finish(None,tuple(tool_results),"RUN_TIMEOUT","诊断整体执行预算已耗尽")
			request=ModelRequest(
				messages=history,
				tools=self._tools,
				model=self._model,
				timeout_seconds=call_timeout,
				request_id=str(uuid4()),
				run_id=run_id,
				response_format=self._response_format,
			)

			started_at=datetime.now(timezone.utc)
			started_clock=perf_counter()
			if events is not None:
				events.emit("model_started",model_round=model_round,model_request_id=request.request_id,model=self._model,
					timeout_seconds=request.timeout_seconds)
			def record_model(error_code=None):
				records.append(ExecutionRecord(
					kind="model",started_at=started_at,finished_at=datetime.now(timezone.utc),
					duration_ms=(perf_counter()-started_clock)*1000,
					status="succeeded" if error_code is None else "failed",error_code=error_code,
					run_id=run_id,model_round=model_round,model_request_id=request.request_id,
				))
				if events is not None:
					events.emit("model_finished",model_round=model_round,model_request_id=request.request_id,
						status=records[-1].status,error_code=error_code,duration_ms=records[-1].duration_ms)

			try:
				call_result=self._gateway.complete(request)
				# HTTP阶段超时不是硬截止时间；拒绝超过共享截止时间才到达的回答。
				if budget is not None:
					budget.check()
			except RunBudgetExceeded:
				record_model("RUN_TIMEOUT")
				return finish(None,tuple(tool_results),"RUN_TIMEOUT","诊断整体执行预算已耗尽")
			except ModelGatewayError as error:
				if budget is not None and budget.remaining()<=0:
					record_model("RUN_TIMEOUT")
					return finish(None,tuple(tool_results),"RUN_TIMEOUT","诊断整体执行预算已耗尽")
				record_model(error.error_code)
				return finish(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code=error.error_code,
					error_message=error.error_message,
				)
			except Exception:
				record_model("MODEL_EXECUTION_FAILED")
				return finish(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code="MODEL_EXECUTION_FAILED",
					error_message="模型调用失败",
				)

			record_model()
			response=call_result.response

			if isinstance(response,(FinalAnswer,StructuredFinalAnswer)):
				return finish(final_answer=response,tool_results=tuple(tool_results),error_code=None)

			if not isinstance(response,(ToolCall,ToolCallBatch)):
				return finish(None,tuple(tool_results),"INVALID_MODEL_RESPONSE","模型返回了无法识别的响应类型")

			calls=(response,) if isinstance(response,ToolCall) else response.calls
			seen_ids={result.tool_call_id for result in tool_results}
			if any(call.tool_call_id in seen_ids for call in calls):
				return finish(None,tuple(tool_results),"MODEL_PROTOCOL_ERROR","工具调用ID不能跨轮重复")

			if len(calls)==1:
				call=calls[0]
				options={} if events is None else {"events":events,"model_round":model_round}
				if budget is not None:
					options["budget"]=budget
				batch_results=(self._runtime.execute(call.tool_name,call.arguments,tool_call_id=call.tool_call_id,**options),)
			else:
				options={} if events is None else {"events":events,"model_round":model_round}
				if budget is not None:
					options["budget"]=budget
				batch_results=self._runtime.execute_many(calls,**options)

			records.extend(
				replace(result.execution_record,run_id=run_id,model_round=model_round)
				for result in batch_results if result.execution_record is not None
			)

			# 证据 ID 由运行时绑定当前 Run，模型只能引用观察结果中的 ID。
			bound_results=tuple(
				replace(result,evidence_id=f"{run_id}-{result.tool_call_id}") if result.ok else result
				for result in batch_results
			)
			tool_results.extend(bound_results)
			# 一条assistant消息声明全部调用，再为每个调用追加对应的tool消息。
			history+=({
				"role":"assistant",
				"tool_calls":[{
					"id":call.tool_call_id,
					"type":"function",
					"function":{
						"name":call.tool_name,
						"arguments":json.dumps(call.arguments,ensure_ascii=False,separators=(",",":")),
					},
				} for call in calls],
			},)
			history+=tuple({
				"role":"tool",
				"tool_call_id":result.tool_call_id,
				"content":json.dumps({
					"evidence_id":result.evidence_id,
					"ok":result.ok,
					"data":result.data,
					"error_code":result.error_code,
					"error_message":result.error_message,
				},ensure_ascii=False,separators=(",",":")),
			} for result in bound_results)

			# 保留现有失败策略：完整收齐本批结果后停止诊断，不生成残缺报告。
			failed=next((result for result in bound_results if not result.ok),None)
			if failed is not None:
				return finish(None,tuple(tool_results),failed.error_code,failed.error_message)
		return finish(
			final_answer=None,
			tool_results=tuple(tool_results),
			error_code="AGENT_MAX_STEPS",
			error_message="Agent Loop达到最大执行步数",
		)
