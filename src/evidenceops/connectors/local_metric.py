import json

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from evidenceops.application.tool_errors import UnknownServiceError
from evidenceops.application.tool_runtime import ToolSpec
from evidenceops.application.run_control import RunControl
from evidenceops.connectors.query_time import parse_query_time


PROJECT_ROOT=Path(__file__).resolve().parents[3]


@dataclass(frozen=True,slots=True)
class MetricSourceConfig:
	service_name:str
	environment:str
	source_path:Path
	read_only:bool=True


METRIC_REGISTRY={
	("order-service","production"):MetricSourceConfig(
		service_name="order-service",
		environment="production",
		source_path=PROJECT_ROOT/"samples"/"metrics"/"order-service.jsonl",
	),
}


def parse_timestamp(value:Any)->datetime:
	if not isinstance(value,str):
		raise ValueError("时间必须是ISO 8601字符串")

	try:
		timestamp=datetime.fromisoformat(value)
	except ValueError as error:
		raise ValueError("时间格式无效") from error

	if timestamp.tzinfo is None or timestamp.utcoffset() is None:
		raise ValueError("时间必须携带时区")

	return timestamp


@dataclass(frozen=True,slots=True)
class LocalMetricQuery:
	service_name:str
	environment:str
	start_time:datetime
	end_time:datetime
	limit:int

	@classmethod
	def from_arguments(cls,arguments:dict[str,Any])->dict[str,Any]:
		allowed_fields={"service_name","environment","start_time","end_time","limit"}
		if set(arguments)-allowed_fields:
			raise ValueError("包含不支持的指标查询参数")

		service_name=arguments.get("service_name")
		environment=arguments.get("environment")
		limit=arguments.get("limit",50)

		if not isinstance(service_name,str) or not service_name.strip():
			raise ValueError("service_name必须是非空字符串")

		if not isinstance(environment,str):
			raise ValueError("environment必须是字符串")

		environment=environment.strip()
		if environment not in ("production","staging"):
			raise ValueError("environment必须是production或staging")

		start_time=parse_query_time(arguments.get("start_time"),"start_time")
		end_time=parse_query_time(arguments.get("end_time"),"end_time")

		if start_time>=end_time:
			raise ValueError("start_time必须早于end_time")

		if (end_time-start_time).total_seconds()>1800:
			raise ValueError("单次查询时间范围不能超过30分钟")

		if not isinstance(limit,int) or isinstance(limit,bool) or not 0<limit<=100:
			raise ValueError("limit必须是1到100之间的整数")

		return {
			"service_name":service_name.strip(),
			"environment":environment,
			"start_time":start_time,
			"end_time":end_time,
			"limit":limit,
		}


def validate_sample(record:dict[str,Any])->None:
	for field in ("active_threads","thread_limit","pending_tasks"):
		value=record.get(field)
		if not isinstance(value,int) or isinstance(value,bool) or value<0:
			raise ValueError(f"{field}必须是非负整数")

	if record["thread_limit"]==0:
		raise ValueError("thread_limit必须大于0")


def query_local_metrics(arguments:dict[str,Any],control:RunControl|None=None)->dict[str,Any]:
	if control is not None:
		control.check()
	query=LocalMetricQuery(**arguments)
	config=METRIC_REGISTRY.get((query.service_name,query.environment))

	if config is None:
		raise UnknownServiceError(f"没有找到已注册指标来源:{query.service_name}/{query.environment}")

	if not config.read_only:
		raise PermissionError("指标来源不是只读来源")

	matches=[]

	# 逐行读取；limit限制返回数量，不限制读取数量。
	with config.source_path.open(encoding="utf-8") as source_file:
		for line_number,raw_line in enumerate(source_file,start=1):
			if control is not None:
				control.check()
			if not raw_line.strip():
				continue

			try:
				record=json.loads(raw_line)

				if not isinstance(record,dict):
					raise ValueError("指标采样必须是JSON对象")

				service_name=record.get("service_name")
				environment=record.get("environment")

				if not isinstance(service_name,str) or not service_name.strip():
					raise ValueError("指标采样缺少有效的service_name")

				if environment not in ("production","staging"):
					raise ValueError("指标采样缺少有效的environment")

				timestamp=parse_timestamp(record.get("timestamp"))
				validate_sample(record)
			except ValueError as error:
				raise ValueError(f"指标文件第{line_number}行无效:{error}") from error

			if service_name!=query.service_name or environment!=query.environment:
				continue

			if not query.start_time<=timestamp<=query.end_time:
				continue

			matches.append((timestamp,{"line_number":line_number,"record":record,}))

	matches.sort(key=lambda sample:sample[0])
	samples=[sample[1] for sample in matches[:query.limit]]

	return {
		"service_name":query.service_name,
		"environment":query.environment,
		"start_time":query.start_time.isoformat(),
		"end_time":query.end_time.isoformat(),
		"samples":samples,
		"total_count":len(matches),
		"returned_count":len(samples),
		"truncated":len(matches)>len(samples),
		"source_ref":str(config.source_path),
		"source_version":"local-metric-jsonl-v1",
	}


def build_local_metric_tool()->ToolSpec:
	return ToolSpec(
		name="query_service_metrics",
		read_only=True,
		validate_arguments=LocalMetricQuery.from_arguments,
		handler=query_local_metrics,
		controlled_handler=query_local_metrics,
		parameters_schema={
			"type":"object",
			"properties":{
				"service_name":{
					"type":"string",
					"description":"已登记的后端服务名称",
				},
				"environment":{
					"type":"string",
					"enum":["production","staging"],
				},
				"start_time":{
					"type":"string",
					"description":"带时区的ISO 8601开始时间，查询窗口最多30分钟",
				},
				"end_time":{
					"type":"string",
					"description":"带时区的ISO 8601结束时间",
				},
				"limit":{
					"type":"integer",
					"minimum":1,
					"maximum":100,
					"description":"按采样时间升序返回最早的若干条采样",
				},
			},
			"required":["service_name","environment","start_time","end_time"],
			"additionalProperties":False,
		},
	)
