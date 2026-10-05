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

		if not isinstance(result.data,dict):
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="工具成功结果必须是JSON对象",
			)

		if result.tool_name=="query_thread_pool_snapshot":
			return self._thread_pool_evidence(run,result)

		if result.tool_name=="query_service_logs":
			return self._log_evidence(run,result)

		if result.tool_name=="query_service_metrics":
			return self._metric_evidence(run,result)

		if result.tool_name=="query_service_config":
			return self._config_evidence(run,result)

		raise ToolCollectionError(
			error_code="UNSUPPORTED_TOOL_RESULT",
			error_message=f"当前Collector不支持工具:{result.tool_name}",
		)

	def _thread_pool_evidence(self,run:DiagnosisRun,result:ToolResult)->Evidence:
		data=result.data
		observed_at=self._parse_observed_at(data.get("observed_at"))
		content=self._build_canonical_content(data)
		content_hash=sha256(content.encode("utf-8")).hexdigest()

		evidence_id=self._require_evidence_id(result)
		service_name=data.get("service_name")
		active_threads=data.get("active_threads")
		thread_limit=data.get("thread_limit")
		pending_tasks=data.get("pending_tasks")

		if not isinstance(service_name,str) or not service_name.strip():
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="线程池结果缺少有效的service_name",
			)

		if not all(
			isinstance(value,int) and not isinstance(value,bool) and value>=0
			for value in (active_threads,thread_limit,pending_tasks)
		):
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="线程池结果中的指标必须是非负整数",
			)

		return Evidence(
			evidence_id=evidence_id,
			run_id=run.run_id,
			source=EvidenceSource.METRIC,
			observed_at=observed_at,
			summary=(
				f"线程池快照：活跃线程 "
				f"{active_threads}/{thread_limit}，"
				f"待处理任务 {pending_tasks}"
			),
			source_ref=(
				"tool:query_thread_pool_snapshot:"
				f"service:{service_name}"
			),
			content_hash=content_hash,
			source_version="mock-v1",
		)

	def _log_evidence(self,run:DiagnosisRun,result:ToolResult)->Evidence:
		data=result.data
		matches=data.get("matches")
		total_count=data.get("total_count")
		returned_count=data.get("returned_count")
		truncated=data.get("truncated")
		service_name=data.get("service_name")
		environment=data.get("environment")
		source_ref=data.get("source_ref")

		if not isinstance(matches,list):
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果中的matches必须是数组",
			)

		if not all(
			isinstance(value,int) and not isinstance(value,bool) and value>=0
			for value in (total_count,returned_count)
		):
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果中的数量字段必须是非负整数",
			)

		if returned_count!=len(matches) or total_count<returned_count:
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果中的数量字段不一致",
			)

		if not isinstance(truncated,bool):
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果中的truncated必须是布尔值",
			)

		if truncated!=(total_count>returned_count):
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果中的截断状态不一致",
			)

		if not isinstance(service_name,str) or not service_name.strip():
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果缺少有效的service_name",
			)

		if not isinstance(environment,str) or not environment.strip():
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果缺少有效的environment",
			)

		if not isinstance(source_ref,str) or not source_ref.strip():
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="日志查询结果缺少有效的source_ref",
			)

		line_numbers=[]

		for match in matches:
			if not isinstance(match,dict):
				raise ToolCollectionError(
					error_code="INVALID_TOOL_RESULT",
					error_message="日志匹配项必须是JSON对象",
				)

			line_number=match.get("line_number")
			record=match.get("record")

			if (
				not isinstance(line_number,int)
				or isinstance(line_number,bool)
				or line_number<=0
				or not isinstance(record,dict)
			):
				raise ToolCollectionError(
					error_code="INVALID_TOOL_RESULT",
					error_message="日志匹配项缺少有效行号或记录",
				)

			line_numbers.append(line_number)

		observed_at=self._parse_observed_at(data.get("observed_at"))
		content=self._build_canonical_content(data)
		content_hash=sha256(content.encode("utf-8")).hexdigest()
		evidence_id=self._require_evidence_id(result)

		if matches:
			line_range=(
				f"lines:{min(line_numbers)}-{max(line_numbers)}"
			)
		else:
			line_range="no-matching-lines"

		return Evidence(
			evidence_id=evidence_id,
			run_id=run.run_id,
			source=EvidenceSource.LOG,
			observed_at=observed_at,
			summary=(
				f"{service_name}({environment})日志查询匹配"
				f"{total_count}条，返回{returned_count}条，"
				f"结果{'已截断' if truncated else '未截断'}"
			),
			source_ref=f"{source_ref}:{line_range}",
			content_hash=content_hash,
			source_version="local-jsonl-v1",
		)

	def _metric_evidence(self,run:DiagnosisRun,result:ToolResult)->Evidence:
		data=result.data
		samples=data.get("samples")
		total_count=data.get("total_count")
		returned_count=data.get("returned_count")
		truncated=data.get("truncated")
		service_name=data.get("service_name")
		environment=data.get("environment")
		source_ref=data.get("source_ref")
		source_version=data.get("source_version")
		line_numbers=[]
		sample_times=[]

		# 校验工具输出；此处的错误不是模型查询参数错误。
		try:
			if not isinstance(samples,list):
				raise ValueError("指标查询结果中的samples必须是数组")

			for field,value in (("total_count",total_count),("returned_count",returned_count)):
				if not isinstance(value,int) or isinstance(value,bool) or value<0:
					raise ValueError(f"{field}必须是非负整数")

			if returned_count!=len(samples) or total_count<returned_count:
				raise ValueError("指标查询结果中的数量字段不一致")

			if not isinstance(truncated,bool) or truncated!=(total_count>returned_count):
				raise ValueError("指标查询结果中的截断状态不一致")

			for field,value in (("service_name",service_name),("source_ref",source_ref),("source_version",source_version)):
				if not isinstance(value,str) or not value.strip():
					raise ValueError(f"指标查询结果缺少有效的{field}")

			if environment not in ("production","staging"):
				raise ValueError("指标查询结果中的environment无效")

			start_time=self._parse_observed_at(data.get("start_time"))
			end_time=self._parse_observed_at(data.get("end_time"))
			if not 0<(end_time-start_time).total_seconds()<=1800:
				raise ValueError("指标查询时间窗口必须大于0且不超过30分钟")

			for sample in samples:
				if not isinstance(sample,dict):
					raise ValueError("指标采样项必须是JSON对象")

				line_number=sample.get("line_number")
				record=sample.get("record")
				if not isinstance(line_number,int) or isinstance(line_number,bool) or line_number<=0:
					raise ValueError("指标采样行号必须是正整数")
				if line_number in line_numbers:
					raise ValueError("指标采样行号不能重复")
				if not isinstance(record,dict):
					raise ValueError("指标采样记录必须是JSON对象")

				if record.get("service_name")!=service_name or record.get("environment")!=environment:
					raise ValueError("指标采样不属于结果声明的服务或环境")

				timestamp=self._parse_observed_at(record.get("timestamp"))
				if not start_time<=timestamp<=end_time:
					raise ValueError("指标采样时间不在查询窗口内")
				if sample_times and timestamp<sample_times[-1]:
					raise ValueError("指标采样必须按时间升序排列")

				for field in ("active_threads","thread_limit","pending_tasks"):
					value=record.get(field)
					if not isinstance(value,int) or isinstance(value,bool) or value<0:
						raise ValueError(f"指标采样中的{field}必须是非负整数")
				if record["thread_limit"]==0:
					raise ValueError("指标采样中的thread_limit必须大于0")

				line_numbers.append(line_number)
				sample_times.append(timestamp)
		except ValueError as error:
			raise ToolCollectionError("INVALID_TOOL_RESULT",str(error)) from error

		if not samples:
			raise ToolCollectionError("NO_METRIC_SAMPLES","查询窗口内没有指标采样，不能生成指标证据")

		evidence_id=self._require_evidence_id(result)
		content=self._build_canonical_content(data)
		content_hash=sha256(content.encode("utf-8")).hexdigest()
		line_range=f"lines:{min(line_numbers)}-{max(line_numbers)}"

		return Evidence(
			evidence_id=evidence_id,
			run_id=run.run_id,
			source=EvidenceSource.METRIC,
			observed_at=sample_times[0],
			summary=(
				f"{service_name}({environment})指标查询匹配{total_count}条，"
				f"返回{returned_count}条，结果{'已截断' if truncated else '未截断'}，"
				f"返回采样时间范围{sample_times[0].isoformat()}至{sample_times[-1].isoformat()}"
			),
			source_ref=f"{source_ref}:{line_range}",
			content_hash=content_hash,
			source_version=source_version,
		)

	def _config_evidence(self,run:DiagnosisRun,result:ToolResult)->Evidence:
		data=result.data
		service_name=data.get("service_name")
		environment=data.get("environment")
		source_ref=data.get("source_ref")
		source_version=data.get("source_version")
		config=data.get("config")
		try:
			for field,value in (("service_name",service_name),("source_ref",source_ref),("source_version",source_version)):
				if not isinstance(value,str) or not value.strip():
					raise ValueError(f"配置查询结果缺少有效的{field}")
			if environment not in ("production","staging"):
				raise ValueError("配置查询结果中的environment无效")
			if not isinstance(config,dict):
				raise ValueError("配置查询结果中的config必须是JSON对象")
			line_number=config.get("line_number")
			record=config.get("record")
			if not isinstance(line_number,int) or isinstance(line_number,bool) or line_number<=0:
				raise ValueError("配置行号必须是正整数")
			if not isinstance(record,dict):
				raise ValueError("配置记录必须是JSON对象")
			if record.get("service_name")!=service_name or record.get("environment")!=environment:
				raise ValueError("配置记录不属于结果声明的服务和环境")
			version=record.get("config_version")
			if not isinstance(version,str) or not version.strip():
				raise ValueError("配置记录缺少有效的config_version")
			if "effective_until" not in record:
				raise ValueError("配置记录必须声明effective_until")
			at_time=self._parse_observed_at(data.get("at_time"))
			start_time=self._parse_observed_at(record.get("effective_from"))
			end_value=record["effective_until"]
			end_time=None if end_value is None else self._parse_observed_at(end_value)
			if end_time is not None and end_time<=start_time:
				raise ValueError("配置失效时间必须晚于生效时间")
			if at_time<start_time or (end_time is not None and at_time>=end_time):
				raise ValueError("返回配置不在查询时刻生效")
			for field in ("thread_pool_size","rpc_timeout_ms","max_retries"):
				value=record.get(field)
				minimum=0 if field=="max_retries" else 1
				if not isinstance(value,int) or isinstance(value,bool) or value<minimum:
					raise ValueError(f"配置中的{field}必须是大于等于{minimum}的整数")
		except ValueError as error:
			raise ToolCollectionError("INVALID_TOOL_RESULT",str(error)) from error

		evidence_id=self._require_evidence_id(result)
		content=self._build_canonical_content(data)
		content_hash=sha256(content.encode("utf-8")).hexdigest()
		return Evidence(
			evidence_id=evidence_id,
			run_id=run.run_id,
			source=EvidenceSource.CONFIG,
			# 配置证据使用版本生效时间，查询时刻单独保留在摘要和工具数据中。
			observed_at=start_time,
			summary=(
				f"{service_name}({environment})在{at_time.isoformat()}生效的配置版本{version}："
				f"线程池容量{record['thread_pool_size']}，RPC超时{record['rpc_timeout_ms']}毫秒，"
				f"最多额外重试{record['max_retries']}次"
			),
			source_ref=f"{source_ref}:line:{line_number}",
			content_hash=content_hash,
			source_version=source_version,
		)

	@staticmethod
	def _require_evidence_id(result:ToolResult)->str:
		evidence_id=result.evidence_id

		if not isinstance(evidence_id,str) or not evidence_id.strip():
			raise ToolCollectionError(
				error_code="MISSING_EVIDENCE_ID",
				error_message="工具结果缺少Evidence ID",
			)

		return evidence_id

	@staticmethod
	def _parse_observed_at(value:Any)->datetime:
		if not isinstance(value,str):
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="工具结果中的observed_at必须是字符串",
			)

		try:
			observed_at=datetime.fromisoformat(value)
		except ValueError as error:
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="工具结果中的observed_at时间格式无效",
			) from error

		if observed_at.tzinfo is None or observed_at.utcoffset() is None:
			raise ToolCollectionError(
				error_code="INVALID_TOOL_RESULT",
				error_message="工具结果中的observed_at必须带时区",
			)

		return observed_at

	@staticmethod
	def _build_canonical_content(data:dict[str,Any])->str:
		return json.dumps(
			data,
			ensure_ascii=False,
			sort_keys=True,
			separators=(",",":"),
		)
