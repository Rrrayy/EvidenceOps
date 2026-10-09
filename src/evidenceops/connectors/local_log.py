import json

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from evidenceops.application.tool_errors import UnknownServiceError
from evidenceops.application.tool_runtime import ToolSpec
from evidenceops.connectors.query_time import parse_query_time


PROJECT_ROOT=Path(__file__).resolve().parents[3]


class ErrorType(StrEnum):
	RPC_TIMEOUT="rpc_timeout"
	THREAD_POOL_EXHAUSTED="thread_pool_exhausted"


@dataclass(frozen=True,slots=True)
class LogSourceConfig:
	service_name:str
	environment:str
	source_path:Path
	parser_type:str="jsonl"
	read_only:bool=True


SERVICE_REGISTRY={
	("order-service","production"):LogSourceConfig(
		service_name="order-service",
		environment="production",
		source_path=PROJECT_ROOT/"samples"/"logs"/"order-service.jsonl",
	),
}


@dataclass(frozen=True,slots=True)
class LocalLogQuery:
	service_name:str
	environment:str
	error_type:ErrorType|None
	symptom:str|None
	start_time:datetime
	end_time:datetime
	keywords:tuple[str,...]
	limit:int

	@classmethod
	def from_arguments(cls,arguments:dict[str,Any])->dict[str,Any]:
		service_name=arguments.get("service_name")
		environment=arguments.get("environment")
		error_type=arguments.get("error_type")
		symptom=arguments.get("symptom")
		start_time=arguments.get("start_time")
		end_time=arguments.get("end_time")
		keywords=arguments.get("keywords",[])
		limit=arguments.get("limit",50)

		if not isinstance(service_name,str) or not service_name.strip():
			raise ValueError("service_name必须是非空字符串")

		if not isinstance(environment,str) or not environment.strip():
			raise ValueError("environment必须是非空字符串")
		environment=environment.strip()
		if environment not in ("production","staging"):
			raise ValueError("environment必须是production或staging")

		if error_type is not None:
			try:
				error_type=ErrorType(error_type)
			except ValueError as error:
				raise ValueError(f"不支持的error_type:{error_type}") from error

		if symptom is not None:
			if not isinstance(symptom,str) or not symptom.strip():
				raise ValueError("symptom必须是非空字符串")
			symptom=symptom.strip()
			if len(symptom)>500:
				raise ValueError("symptom不能超过500个字符")

		if error_type is None and symptom is None:
			raise ValueError("error_type和symptom至少提供一个")

		start_time=parse_query_time(start_time,"start_time")
		end_time=parse_query_time(end_time,"end_time")

		if start_time>=end_time:
			raise ValueError("start_time必须早于end_time")

		if (end_time-start_time).total_seconds()>1800:
			raise ValueError("单次查询时间范围不能超过30分钟")

		if not isinstance(keywords,list) or len(keywords)>5:
			raise ValueError("keywords必须是最多5个字符串的数组")

		normalized_keywords=tuple(keyword.strip() for keyword in keywords if isinstance(keyword,str) and keyword.strip())

		if len(normalized_keywords)!=len(keywords):
			raise ValueError("keywords中的每一项都必须是非空字符串")

		if not isinstance(limit,int) or isinstance(limit,bool) or not 0<limit<=100:
			raise ValueError("limit必须是1到100之间的整数")

		return {
			"service_name":service_name.strip(),
			"environment":environment,
			"error_type":error_type,
			"symptom":symptom,
			"start_time":start_time,
			"end_time":end_time,
			"keywords":normalized_keywords,
			"limit":limit,
		}


def query_local_logs(arguments:dict[str,Any])->dict[str,Any]:
	query=LocalLogQuery(**arguments)
	config=SERVICE_REGISTRY.get((query.service_name,query.environment))

	if config is None:
		raise UnknownServiceError(f"没有找到已注册服务:{query.service_name}/{query.environment}")

	if not config.read_only:
		raise PermissionError("日志来源不是只读来源")

	if not config.source_path.exists():
		raise FileNotFoundError(f"日志来源不存在:{config.source_path}")

	matches=[]

	for line_number,raw_line in enumerate(config.source_path.read_text(encoding="utf-8").splitlines(),start=1):
		if not raw_line.strip():
			continue

		try:
			record=json.loads(raw_line)
			observed_at=datetime.fromisoformat(record["timestamp"])
		except (ValueError,KeyError,json.JSONDecodeError):
			continue

		if not query.start_time<=observed_at<=query.end_time:
			continue

		if (query.error_type is not None and record.get("error_type")!=query.error_type.value):
			continue

		search_text=" ".join(str(record.get(field,"")) for field in ("message","error_type","dependency")).lower()

		if query.symptom is not None and query.symptom.lower() not in search_text:
			continue

		if any(keyword.lower() not in search_text for keyword in query.keywords):
			continue

		matches.append({"line_number":line_number,"record":record,})

	total_count=len(matches)
	return {
		"service_name":query.service_name,
		"environment":query.environment,
		"matches":matches[:query.limit],
		"total_count":total_count,
		"returned_count":min(total_count,query.limit),
		"truncated":total_count>query.limit,
		"source_ref":str(config.source_path),
		"observed_at":(
			matches[0]["record"]["timestamp"]
			if matches
			else query.end_time.isoformat()
		),
	}


def build_local_log_tool()->ToolSpec:
	return ToolSpec(
		name="query_service_logs",
		read_only=True,
		validate_arguments=LocalLogQuery.from_arguments,
		handler=query_local_logs,
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
				"error_type":{
					"type":"string",
					"enum":[
						ErrorType.RPC_TIMEOUT.value,
						ErrorType.THREAD_POOL_EXHAUSTED.value,
					],
				},
				"symptom":{
					"type":"string",
					"maxLength":500,
					"description":"未知故障的受限描述",
				},
				"start_time":{
					"type":"string",
					"description":"带时区的ISO 8601开始时间",
				},
				"end_time":{
					"type":"string",
					"description":"带时区的ISO 8601结束时间",
				},
				"keywords":{
					"type":"array",
					"items":{"type":"string"},
					"maxItems":5,
				},
				"limit":{
					"type":"integer",
					"minimum":1,
					"maximum":100,
				},
			},
			"required":[
				"service_name",
				"environment",
				"start_time",
				"end_time",
			],
			"additionalProperties":False,
		},
	)
