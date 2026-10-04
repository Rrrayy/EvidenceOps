import json
from dataclasses import replace

from datetime import datetime
from hashlib import sha256
from typing import Any

from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.application.tool_runtime import ToolResult,ToolRuntime
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence,EvidenceSource


class ToolEvidenceCollector:
	def __init__(self,tool_runtime:ToolRuntime,service_name:str)->None:
		if not service_name.strip():
			raise ValueError("service_name不能为空")

		self._tool_runtime=tool_runtime
		self._service_name=service_name

	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:
		result=self._tool_runtime.execute(
			"query_thread_pool_snapshot",
			{"service_name":self._service_name},
		)
		if result.ok:
			result=replace(
				result,
				evidence_id=f"{run.run_id}-direct-tool-collector",
			)

		return (self._evidence_from_result(run,result),)

	def collect_result(self,run:DiagnosisRun,result:ToolResult)->Evidence:
		return self._evidence_from_result(run,result)

	def _evidence_from_result(self,run:DiagnosisRun,result:ToolResult)->Evidence:
		if not result.ok:
			raise ToolCollectionError(
				error_code=result.error_code or "TOOL_EXECUTION_FAILED",
				error_message=result.error_message or "工具执行失败",
			)

		if result.tool_name!="query_thread_pool_snapshot":
			raise ToolCollectionError(
				error_code="UNSUPPORTED_TOOL_RESULT",
				error_message="当前Collector不支持该工具结果",
			)

		if not isinstance(result.data,dict):
			raise TypeError("工具成功结果必须是JSON对象")

		data=result.data
		observed_at=self._parse_observed_at(data.get("observed_at"))
		content=self._build_canonical_content(data)
		content_hash=sha256(content.encode("utf-8")).hexdigest()

		summary=(
			f"线程池快照：活跃线程 "
			f"{data['active_threads']}/{data['thread_limit']}，"
			f"待处理任务 {data['pending_tasks']}"
		)

		evidence_id = result.evidence_id

		if not isinstance(evidence_id, str) or not evidence_id.strip():
			raise ToolCollectionError(
				error_code="MISSING_EVIDENCE_ID",
				error_message="工具结果缺少Evidence ID",
			)

		return Evidence(
			evidence_id=evidence_id,
			run_id=run.run_id,
			source=EvidenceSource.METRIC,
			observed_at=observed_at,
			summary=summary,
			source_ref=(
				"tool:query_thread_pool_snapshot:"
				f"service:{data['service_name']}"
			),
			content_hash=content_hash,
			source_version="mock-v1",
		)

	@staticmethod
	def _parse_observed_at(value:Any)->datetime:
		if not isinstance(value,str):
			raise ValueError("工具结果中的observed_at必须是字符串")

		observed_at=datetime.fromisoformat(value)

		if observed_at.tzinfo is None or observed_at.utcoffset() is None:
			raise ValueError("工具结果中的observed_at必须带时区")

		return observed_at

	@staticmethod
	def _build_canonical_content(data:dict[str,Any])->str:
		return json.dumps(
			data,
			ensure_ascii=False,
			sort_keys=True,
			separators=(",",":"),
		)
