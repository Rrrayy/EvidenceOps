from dataclasses import dataclass
from typing import Any

from evidenceops.application.tool_runtime import ToolSpec


@dataclass(frozen=True,slots=True)
class ThreadPoolSnapshotRequest:
	service_name:str

	@classmethod
	def from_arguments(cls,arguments:dict[str,Any])->dict[str,Any]:
		service_name=arguments.get("service_name")

		if not isinstance(service_name,str):
			raise ValueError("service_name必须是字符串")

		if not service_name.strip():
			raise ValueError("service_name不能为空")

		return {
			"service_name":service_name.strip(),
		}


def query_thread_pool_snapshot(arguments:dict[str,Any])->dict[str,Any]:
	service_name=arguments["service_name"]

	if service_name!="order-service":
		raise LookupError(f"没有找到服务:{service_name}")

	return {
		"service_name":service_name,
		"active_threads":64,
		"thread_limit":64,
		"pending_tasks":12,
		"observed_at":"2026-10-01T10:00:00+08:00",
	}


def build_thread_pool_tool()->ToolSpec:
	return ToolSpec(
		name="query_thread_pool_snapshot",
		read_only=True,
		validate_arguments=ThreadPoolSnapshotRequest.from_arguments,
		handler=query_thread_pool_snapshot,
	)