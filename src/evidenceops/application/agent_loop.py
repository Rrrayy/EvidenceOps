from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from evidenceops.application.llm_gateway import (
	LLMGateway,
	ModelGatewayError,
)
from evidenceops.application.model_protocol import (
	FinalAnswer,
	ModelRequest,
	ToolCall,
)
from evidenceops.application.tool_runtime import ToolResult,ToolRuntime


@dataclass(frozen=True,slots=True)
class AgentLoopResult:
	final_answer:str|None
	tool_results:tuple[ToolResult,...]
	error_code:str|None


class AgentLoop:
	def __init__(
		self,
		gateway:LLMGateway,
		runtime:ToolRuntime,
		tools:tuple[dict[str,Any],...]=(),
		model:str="mock-model",
		timeout_seconds:float=10.0,
		max_steps:int=3,
	)->None:
		if not isinstance(model,str) or not model.strip():
			raise ValueError("model不能为空")

		if timeout_seconds<=0:
			raise ValueError("timeout_seconds必须大于0")

		if max_steps<=0:
			raise ValueError("max_steps必须大于0")

		self._gateway=gateway
		self._runtime=runtime
		self._tools=tools
		self._model=model
		self._timeout_seconds=timeout_seconds
		self._max_steps=max_steps

	def run(self,prompt:str,run_id:str|None=None)->AgentLoopResult:
		if not isinstance(prompt,str) or not prompt.strip():
			raise ValueError("prompt不能为空")

		if run_id is None:
			run_id=str(uuid4())

		if not isinstance(run_id,str) or not run_id.strip():
			raise ValueError("run_id不能为空")

		history:tuple[dict[str,Any],...]=(
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
			)

			try:
				call_result=self._gateway.complete(request)
			except ModelGatewayError as error:
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code=error.error_code,
				)
			except Exception:
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code="MODEL_EXECUTION_FAILED",
				)

			response=call_result.response

			if isinstance(response,FinalAnswer):
				return AgentLoopResult(
					final_answer=response.text,
					tool_results=tuple(tool_results),
					error_code=None,
				)

			if not isinstance(response,ToolCall):
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code="INVALID_MODEL_RESPONSE",
				)

			tool_result=self._runtime.execute(
				response.tool_name,
				response.arguments,
				tool_call_id=response.tool_call_id,
			)

			tool_results.append(tool_result)

			history+=(
				{
					"role":"assistant",
					"tool_call_id":response.tool_call_id,
					"tool_name":response.tool_name,
					"arguments":response.arguments,
				},
				{
					"role":"tool",
					"tool_call_id":tool_result.tool_call_id,
					"tool_name":tool_result.tool_name,
					"ok":tool_result.ok,
					"data":tool_result.data,
					"error_code":tool_result.error_code,
					"error_message":tool_result.error_message,
				},
			)

			if not tool_result.ok:
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code=tool_result.error_code,
				)

		return AgentLoopResult(
			final_answer=None,
			tool_results=tuple(tool_results),
			error_code="AGENT_MAX_STEPS",
		)