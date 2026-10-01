from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True,slots=True)
class ToolResult:
	tool_name:str
	ok:bool
	data:Any=None
	error_code:str|None=None
	error_message:str|None=None

	def __post_init__(self)->None:
		if not self.tool_name.strip():
			raise ValueError("tool_name不能为空")

		if self.ok and self.error_code is not None:
			raise ValueError("成功结果不能携带error_code")

		if self.ok and self.error_message is not None:
			raise ValueError("成功结果不能携带error_message")

		if not self.ok and not self.error_code:
			raise ValueError("失败结果必须携带error_code")


@dataclass(frozen=True,slots=True)
class ToolSpec:
	name:str
	read_only:bool
	validate_arguments:Callable[[dict[str,Any]],dict[str,Any]]
	handler:Callable[[dict[str,Any]],Any]

	def __post_init__(self)->None:
		if not self.name.strip():
			raise ValueError("工具名称不能为空")

		if not callable(self.validate_arguments):
			raise TypeError("validate_arguments必须可调用")

		if not callable(self.handler):
			raise TypeError("handler必须可调用")


class ToolRuntime:
	def __init__(
		self,
		tools:tuple[ToolSpec,...],
		timeout_seconds:float=1.0,
	)->None:
		if timeout_seconds<=0:
			raise ValueError("timeout_seconds必须大于0")

		self._tools={tool.name:tool for tool in tools}
		self._timeout_seconds=timeout_seconds
		self._executor=ThreadPoolExecutor(max_workers=4)

	def execute(
		self,
		tool_name:str,
		arguments:dict[str,Any],
	)->ToolResult:
		tool=self._tools.get(tool_name)

		if tool is None:
			return ToolResult(
				tool_name,
				False,
				error_code="UNKNOWN_TOOL",
				error_message="工具不存在",
			)

		if not isinstance(arguments,dict):
			return ToolResult(
				tool_name,
				False,
				error_code="INVALID_ARGUMENTS",
				error_message="工具参数必须是JSON对象",
			)

		if not tool.read_only:
			return ToolResult(
				tool_name,
				False,
				error_code="TOOL_POLICY_DENIED",
				error_message="当前运行时只允许只读工具",
			)

		try:
			normalized_arguments=tool.validate_arguments(arguments)
		except ValueError as error:
			return ToolResult(
				tool_name,
				False,
				error_code="INVALID_ARGUMENTS",
				error_message=str(error),
			)

		future=self._executor.submit(
			tool.handler,
			normalized_arguments,
		)

		try:
			data=future.result(timeout=self._timeout_seconds)
		except FutureTimeout:
			future.cancel()

			return ToolResult(
				tool_name,
				False,
				error_code="TOOL_TIMEOUT",
				error_message="工具执行超过时间限制",
			)
		except Exception as error:
			return ToolResult(
				tool_name,
				False,
				error_code="TOOL_EXECUTION_FAILED",
				error_message=str(error),
			)

		return ToolResult(
			tool_name,
			True,
			data=data,
		)

	def close(self)->None:
		self._executor.shutdown(
			wait=False,
			cancel_futures=True,
		)