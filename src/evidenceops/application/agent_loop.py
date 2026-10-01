from dataclasses import dataclass
from typing import Any,Protocol

from evidenceops.application.tool_runtime import ToolResult,ToolRuntime


@dataclass(frozen=True,slots=True)
class ToolCall:
	tool_name:str
	arguments:dict[str,Any]

	def __post_init__(self)->None:
		if not isinstance(self.tool_name,str) or not self.tool_name.strip():
			raise ValueError("tool_name不能为空")

		if not isinstance(self.arguments,dict):
			raise TypeError("arguments必须是字典")


@dataclass(frozen=True,slots=True)
class FinalAnswer:
	text:str

	def __post_init__(self)->None:
		if not isinstance(self.text,str) or not self.text.strip():
			raise ValueError("最终答案不能为空")


ModelResponse=ToolCall|FinalAnswer


class AgentModel(Protocol):
	def respond(self,history:tuple[dict[str,Any],...])->ModelResponse:
		...


@dataclass(frozen=True,slots=True)
class AgentLoopResult:
	final_answer:str|None
	tool_results:tuple[ToolResult,...]
	error_code:str|None


class AgentLoop:
	def __init__(self,model:AgentModel,runtime:ToolRuntime,max_steps:int=3)->None:
		if max_steps<=0:
			raise ValueError("max_steps必须大于0")

		self._model=model
		self._runtime=runtime
		self._max_steps=max_steps

	def run(self,prompt:str)->AgentLoopResult:
		if not prompt.strip():
			raise ValueError("prompt不能为空")

		history:tuple[dict[str,Any],...]=(
			{
				"role":"user",
				"content":prompt,
			},
		)

		tool_results:list[ToolResult]=[]

		for _ in range(self._max_steps):
			try:
				response=self._model.respond(history)
			except Exception:
				return AgentLoopResult(
					final_answer=None,
					tool_results=tuple(tool_results),
					error_code="MODEL_EXECUTION_FAILED",
				)

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
			)

			tool_results.append(tool_result)

			history+=(
				{
					"role":"assistant",
					"tool_name":response.tool_name,
					"arguments":response.arguments,
				},
				{
					"role":"tool",
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