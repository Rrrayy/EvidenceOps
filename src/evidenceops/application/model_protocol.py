from dataclasses import dataclass
from typing import Any,Protocol


@dataclass(frozen=True,slots=True)
class ToolCall:
	tool_call_id:str
	tool_name:str
	arguments:dict[str,Any]

	def __post_init__(self)->None:
		if not isinstance(self.tool_call_id,str) or not self.tool_call_id.strip():
			raise ValueError("tool_call_id不能为空")

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


@dataclass(frozen=True,slots=True)
class StructuredFinalAnswer:
	data:dict[str,Any]

	def __post_init__(self)->None:
		if not isinstance(self.data,dict):
			raise TypeError("结构化最终答案必须是JSON对象")

		if not self.data:
			raise ValueError("结构化最终答案不能为空")


@dataclass(frozen=True,slots=True)
class ToolCallBatch:
	calls:tuple[ToolCall,...]

	def __post_init__(self)->None:
		if not isinstance(self.calls,tuple) or not 1<=len(self.calls)<=16:
			raise ValueError("每轮工具调用必须是包含1至16项的元组")
		if any(not isinstance(call,ToolCall) for call in self.calls):
			raise TypeError("工具调用批次只能包含ToolCall")
		if len({call.tool_call_id for call in self.calls})!=len(self.calls):
			raise ValueError("同一批次的工具调用ID不能重复")


ModelResponse=ToolCall|ToolCallBatch|FinalAnswer|StructuredFinalAnswer


@dataclass(frozen=True,slots=True)
class ModelRequest:
	messages:tuple[dict[str,Any],...]
	tools:tuple[dict[str,Any],...]
	model:str
	timeout_seconds:float
	request_id:str
	run_id:str
	response_format:str="text"

	def __post_init__(self)->None:
		if not isinstance(self.messages,tuple):
			raise TypeError("messages必须是元组")

		if not isinstance(self.tools,tuple):
			raise TypeError("tools必须是元组")

		if not isinstance(self.model,str) or not self.model.strip():
			raise ValueError("model不能为空")

		if self.timeout_seconds<=0:
			raise ValueError("timeout_seconds必须大于0")

		if not isinstance(self.request_id,str) or not self.request_id.strip():
			raise ValueError("request_id不能为空")

		if not isinstance(self.run_id,str) or not self.run_id.strip():
			raise ValueError("run_id不能为空")

		if self.response_format not in ("text","json_object"):
			raise ValueError(
				"response_format必须是text或json_object"
			)

@dataclass(frozen=True,slots=True)
class ModelUsage:
	prompt_tokens:int|None
	completion_tokens:int|None
	total_tokens:int|None

	def __post_init__(self)->None:
		for token_value in (
			self.prompt_tokens,
			self.completion_tokens,
			self.total_tokens,
		):
			if token_value is not None and token_value<0:
				raise ValueError("Token数量不能为负数")


@dataclass(frozen=True,slots=True)
class ProviderResponse:
	response:ModelResponse
	model:str
	usage:ModelUsage|None

	def __post_init__(self)->None:
		if not isinstance(
			self.response,
			(ToolCall,ToolCallBatch,FinalAnswer,StructuredFinalAnswer),
		):
			raise TypeError(
				"response必须是ToolCall、ToolCallBatch、FinalAnswer或StructuredFinalAnswer"
			)

		if not isinstance(self.model,str) or not self.model.strip():
			raise ValueError("model不能为空")


@dataclass(frozen=True,slots=True)
class ModelCallResult:
	response:ModelResponse
	provider:str
	model:str
	latency_ms:float
	usage:ModelUsage|None
	request_id:str

	def __post_init__(self)->None:
		if not isinstance(
			self.response,
			(ToolCall,ToolCallBatch,FinalAnswer,StructuredFinalAnswer),
		):
			raise TypeError(
				"response必须是ToolCall、ToolCallBatch、FinalAnswer或StructuredFinalAnswer"
			)

		if not isinstance(self.provider,str) or not self.provider.strip():
			raise ValueError("provider不能为空")

		if not isinstance(self.model,str) or not self.model.strip():
			raise ValueError("model不能为空")

		if self.latency_ms<0:
			raise ValueError("latency_ms不能为负数")

		if not isinstance(self.request_id,str) or not self.request_id.strip():
			raise ValueError("request_id不能为空")


class ModelProviderError(RuntimeError):
	def __init__(self,error_code:str,error_message:str)->None:
		super().__init__(error_message)
		self.error_code=error_code
		self.error_message=error_message


class ModelProvider(Protocol):
	def complete(self,request:ModelRequest)->ProviderResponse:
		...
