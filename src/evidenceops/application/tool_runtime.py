from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from collections.abc import Callable
from dataclasses import dataclass,field,replace
from datetime import datetime,timezone
from threading import Lock
from time import perf_counter
from typing import Any

from evidenceops.application.tool_errors import UnknownServiceError
from evidenceops.application.model_protocol import ToolCall,ToolCallBatch
from evidenceops.application.execution_record import ExecutionRecord


@dataclass(frozen=True,slots=True)
class ToolResult:
	tool_name:str
	ok:bool
	data:Any=None
	error_code:str|None=None
	error_message:str|None=None
	tool_call_id:str|None=None
	evidence_id:str|None=None
	execution_record:ExecutionRecord|None=None

	def __post_init__(self)->None:
		if not self.tool_name.strip():
			raise ValueError("tool_name不能为空")

		if self.tool_call_id is not None and (not isinstance(self.tool_call_id,str) or not self.tool_call_id.strip()):
			raise ValueError("tool_call_id不能为空")

		if self.evidence_id is not None and (not isinstance(self.evidence_id,str) or not self.evidence_id.strip()):
			raise ValueError("evidence_id不能为空")

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
	parameters_schema:dict[str,Any]=field(default_factory=dict)

	def __post_init__(self)->None:
		if not self.name.strip():
			raise ValueError("工具名称不能为空")

		if not callable(self.validate_arguments):
			raise TypeError("validate_arguments必须可调用")

		if not callable(self.handler):
			raise TypeError("handler必须可调用")

		if not isinstance(self.parameters_schema,dict):
			raise TypeError("parameters_schema必须是字典")

	def to_model_schema(self)->dict[str,Any]:
		return {"type":"function","function":{"name":self.name,"parameters":self.parameters_schema,},}


class ToolRuntime:
	def __init__(self,tools:tuple[ToolSpec,...],timeout_seconds:float=1.0)->None:
		if timeout_seconds<=0:
			raise ValueError("timeout_seconds必须大于0")

		self._tools={tool.name:tool for tool in tools}
		self._timeout_seconds=timeout_seconds
		self._executor=ThreadPoolExecutor(max_workers=4)

	def execute(self,tool_name:str,arguments:dict[str,Any],tool_call_id:str|None=None)->ToolResult:
		started_at=datetime.now(timezone.utc)
		started_clock=perf_counter()
		# 仅记录已知只读查询的标量条件；不保存路径、密钥或任意工具负载。
		query_arguments=None
		if tool_name in ("query_service_logs","query_service_metrics","query_service_config") and isinstance(arguments,dict):
			fields=("service_name","environment","start_time","end_time","at_time","error_type","limit")
			query_arguments={
				field:value for field,value in arguments.items()
				if field in fields and (value is None or isinstance(value,(str,int,float,bool)))
			}
		handler_times={}
		timing_lock=Lock()
		try:
			result=self._execute(tool_name,arguments,tool_call_id,handler_times,timing_lock)
		except Exception as error:
			result=ToolResult(tool_name,False,error_code="TOOL_EXECUTION_FAILED",error_message=str(error),tool_call_id=tool_call_id)
		finished_at=datetime.now(timezone.utc)
		with timing_lock:
			times=dict(handler_times)
		record=ExecutionRecord(
			kind="tool",started_at=started_at,finished_at=finished_at,
			duration_ms=(perf_counter()-started_clock)*1000,
			status="succeeded" if result.ok else "failed",error_code=result.error_code,
			tool_name=tool_name,tool_call_id=tool_call_id,
			handler_started_at=times.get("started_at"),handler_finished_at=times.get("finished_at"),
			query_arguments=query_arguments,
		)
		return replace(result,execution_record=record)

	def _execute(
		self,
		tool_name:str,
		arguments:dict[str,Any],
		tool_call_id:str|None=None,
		handler_times:dict|None=None,
		timing_lock:Any=None,
	)->ToolResult:
		tool=self._tools.get(tool_name)

		if tool is None:
			return ToolResult(
				tool_name,
				False,
				error_code="UNKNOWN_TOOL",
				error_message="工具不存在",
				tool_call_id=tool_call_id,
			)

		if not isinstance(arguments,dict):
			return ToolResult(
				tool_name,
				False,
				error_code="INVALID_ARGUMENTS",
				error_message="工具参数必须是JSON对象",
				tool_call_id=tool_call_id,
			)

		if not tool.read_only:
			return ToolResult(
				tool_name,
				False,
				error_code="TOOL_POLICY_DENIED",
				error_message="当前运行时只允许只读工具",
				tool_call_id=tool_call_id,
			)

		try:
			normalized_arguments=tool.validate_arguments(arguments)
		except ValueError as error:
			return ToolResult(
				tool_name,
				False,
				error_code="INVALID_ARGUMENTS",
				error_message=str(error),
				tool_call_id=tool_call_id,
			)

		def invoke_handler():
			with timing_lock:
				handler_times["started_at"]=datetime.now(timezone.utc)
			try:
				return tool.handler(normalized_arguments)
			finally:
				with timing_lock:
					handler_times["finished_at"]=datetime.now(timezone.utc)

		future=self._executor.submit(invoke_handler)

		try:
			data=future.result(timeout=self._timeout_seconds)
		except FutureTimeout:
			# 只能取消尚未开始的任务，不能强杀已经运行的 handler 线程。
			future.cancel()

			return ToolResult(
				tool_name,
				False,
				error_code="TOOL_TIMEOUT",
				error_message="工具执行超过时间限制",
				tool_call_id=tool_call_id,
			)
		except UnknownServiceError as error:
			return ToolResult(
				tool_name,
				False,
				error_code="UNKNOWN_SERVICE",
				error_message=str(error),
				tool_call_id=tool_call_id,
			)
		except PermissionError as error:
			return ToolResult(
				tool_name,
				False,
				error_code="ACCESS_DENIED",
				error_message=str(error),
				tool_call_id=tool_call_id,
			)
		except FileNotFoundError as error:
			return ToolResult(
				tool_name,
				False,
				error_code="TOOL_SOURCE_NOT_FOUND",
				error_message=str(error),
				tool_call_id=tool_call_id,
			)
		except Exception as error:
			return ToolResult(
				tool_name,
				False,
				error_code="TOOL_EXECUTION_FAILED",
				error_message=str(error),
				tool_call_id=tool_call_id,
			)

		return ToolResult(tool_name,True,data=data,tool_call_id=tool_call_id)

	def execute_many(self,calls:tuple[ToolCall,...])->tuple[ToolResult,...]:
		ToolCallBatch(calls)
		# 调度线程与handler线程池分开，避免线程等待自身池内任务而死锁。
		with ThreadPoolExecutor(max_workers=4) as dispatcher:
			futures=[dispatcher.submit(self.execute,call.tool_name,call.arguments,call.tool_call_id) for call in calls]
			# 按调用顺序汇总；任务在提交后已经并发运行。
			return tuple(future.result() for future in futures)

	def close(self)->None:
		self._executor.shutdown(wait=False,cancel_futures=True)
