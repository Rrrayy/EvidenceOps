import json

from dataclasses import dataclass,replace
from typing import Any
from uuid import uuid4

from evidenceops.application.llm_gateway import LLMGateway,ModelGatewayError
from evidenceops.application.model_protocol import FinalAnswer,ModelRequest,StructuredFinalAnswer,ToolCall
from evidenceops.application.tool_runtime import ToolResult,ToolRuntime,ToolSpec


@dataclass(frozen=True,slots=True)
class AgentLoopResult:
	final_answer:FinalAnswer|StructuredFinalAnswer|None
	tool_results:tuple[ToolResult,...]
	error_code:str|None
	error_message:str|None=None


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
			raise ValueError(
				"response_format必须是text或json_object"
			)

		self._gateway=gateway
		self._runtime=runtime
		self._tools=tuple(
			tool.to_model_schema()
			if isinstance(tool,ToolSpec)
			else tool
			for tool in tools
		)
		self._model=model
		self._timeout_seconds=timeout_seconds
		self._max_steps=max_steps
		self._response_format=response_format

	def run(self,prompt:str,run_id:str|None=None)->AgentLoopResult:
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
					),
				},
				{
					"role":"user",
					"content":prompt,
				},
			)
		else:
			history=(
			{
				"role":"user",
				"content":prompt,
			},
		)

		tool_results:list[ToolResult]=[]

		for _ in range(self._max_steps):
			request=ModelRequest(
				messages=history,
				tools=self._tools,
				model=self._model,
				timeout_seconds=self._timeout_seconds,
				request_id=str(uuid4()),
				run_id=run_id,
				response_format=self._response_format,
			)

			try:
				call_result=self._gateway.complete(request)
			except ModelGatewayError as error:
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code=error.error_code,
					error_message=error.error_message,
				)
			except Exception:
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code="MODEL_EXECUTION_FAILED",
					error_message="模型调用失败",
				)

			response=call_result.response

			if isinstance(response,(FinalAnswer,StructuredFinalAnswer)):
				return AgentLoopResult(
					final_answer=response,
					tool_results=tuple(tool_results),
					error_code=None,
				)

			if not isinstance(response,ToolCall):
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code="INVALID_MODEL_RESPONSE",
					error_message="模型返回了无法识别的响应类型",
				)

			tool_result = self._runtime.execute(
				response.tool_name,
				response.arguments,
				tool_call_id=response.tool_call_id,
			)

			if tool_result.ok:
				evidence_id = f"{run_id}-{response.tool_call_id}"
				tool_result = replace(
					tool_result,
					evidence_id=evidence_id,
				)

			tool_results.append(tool_result)

			history += (
				{
					"role":"assistant",
					"tool_calls":[
						{
							"id":response.tool_call_id,
							"type":"function",
							"function":{
								"name":response.tool_name,
								"arguments":json.dumps(
									response.arguments,
									ensure_ascii=False,
									separators=(",",":"),
								),
							},
						},
					],
				},
				{
					"role":"tool",
					"tool_call_id":tool_result.tool_call_id,
					"content":json.dumps(
						{
							"evidence_id":tool_result.evidence_id,
							"ok":tool_result.ok,
							"data":tool_result.data,
							"error_code":tool_result.error_code,
							"error_message":tool_result.error_message,
						},
						ensure_ascii=False,
						separators=(",",":"),
					),
				},
			)

			if not tool_result.ok:
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code=tool_result.error_code,
					error_message=tool_result.error_message,
				)

		return AgentLoopResult(
			final_answer=None,
			tool_results=tuple(tool_results),
			error_code="AGENT_MAX_STEPS",
			error_message="Agent Loop达到最大执行步数",
		)
