import json

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from evidenceops.application.tool_errors import UnknownServiceError
from evidenceops.application.tool_runtime import ToolSpec
from evidenceops.connectors.query_time import parse_query_time


PROJECT_ROOT=Path(__file__).resolve().parents[3]


@dataclass(frozen=True,slots=True)
class ConfigSource:
	service_name:str
	environment:str
	source_path:Path
	read_only:bool=True


CONFIG_REGISTRY={
	("order-service","production"):ConfigSource(
		"order-service","production",PROJECT_ROOT/"samples"/"configs"/"order-service.jsonl",
	),
}


def parse_config_time(value:Any)->datetime:
	if not isinstance(value,str):
		raise ValueError("配置时间必须是ISO 8601字符串")
	try:
		timestamp=datetime.fromisoformat(value)
	except ValueError as error:
		raise ValueError("配置时间格式无效") from error
	if timestamp.tzinfo is None or timestamp.utcoffset() is None:
		raise ValueError("配置时间必须携带时区")
	return timestamp


@dataclass(frozen=True,slots=True)
class LocalConfigQuery:
	service_name:str
	environment:str
	at_time:datetime

	@classmethod
	def from_arguments(cls,arguments:dict[str,Any])->dict[str,Any]:
		if set(arguments)-{"service_name","environment","at_time"}:
			raise ValueError("包含不支持的配置查询参数")
		service_name=arguments.get("service_name")
		environment=arguments.get("environment")
		if not isinstance(service_name,str) or not service_name.strip():
			raise ValueError("service_name必须是非空字符串")
		if not isinstance(environment,str) or environment.strip() not in ("production","staging"):
			raise ValueError("environment必须是production或staging")
		return {
			"service_name":service_name.strip(),
			"environment":environment.strip(),
			"at_time":parse_query_time(arguments.get("at_time"),"at_time"),
		}


def query_local_config(arguments:dict[str,Any])->dict[str,Any]:
	query=LocalConfigQuery(**arguments)
	source=CONFIG_REGISTRY.get((query.service_name,query.environment))
	if source is None:
		raise UnknownServiceError(f"没有找到已注册配置来源:{query.service_name}/{query.environment}")
	if not source.read_only:
		raise PermissionError("配置来源不是只读来源")

	matches=[]
	versions=set()
	with source.source_path.open(encoding="utf-8") as source_file:
		for line_number,raw_line in enumerate(source_file,start=1):
			if not raw_line.strip():
				continue
			try:
				record=json.loads(raw_line)
				if not isinstance(record,dict):
					raise ValueError("配置记录必须是JSON对象")
				if record.get("service_name")!=query.service_name or record.get("environment")!=query.environment:
					raise ValueError("配置记录不属于已登记的服务和环境")
				version=record.get("config_version")
				if not isinstance(version,str) or not version.strip():
					raise ValueError("config_version必须是非空字符串")
				if version in versions:
					raise ValueError("config_version不能重复")
				versions.add(version)
				if "effective_until" not in record:
					raise ValueError("配置记录必须声明effective_until，未结束时使用null")
				start_time=parse_config_time(record.get("effective_from"))
				end_value=record["effective_until"]
				end_time=None if end_value is None else parse_config_time(end_value)
				if end_time is not None and end_time<=start_time:
					raise ValueError("配置失效时间必须晚于生效时间")
				for field in ("thread_pool_size","rpc_timeout_ms","max_retries"):
					value=record.get(field)
					minimum=0 if field=="max_retries" else 1
					if not isinstance(value,int) or isinstance(value,bool) or value<minimum:
						raise ValueError(f"{field}必须是大于等于{minimum}的整数")
				# 生效区间左闭右开；切换时刻只属于新版本。
				if start_time<=query.at_time and (end_time is None or query.at_time<end_time):
					matches.append({"line_number":line_number,"record":record})
			except ValueError as error:
				raise ValueError(f"配置文件第{line_number}行无效:{error}") from error

	if not matches:
		raise LookupError(f"查询时刻没有生效的配置版本:{query.at_time.isoformat()}")
	if len(matches)>1:
		raise ValueError("查询时刻存在多个生效配置版本，拒绝选择歧义结果")

	return {
		"service_name":query.service_name,
		"environment":query.environment,
		"at_time":query.at_time.isoformat(),
		"config":matches[0],
		"source_ref":str(source.source_path),
		"source_version":"local-config-jsonl-v1",
	}


def build_local_config_tool()->ToolSpec:
	return ToolSpec(
		name="query_service_config",
		read_only=True,
		validate_arguments=LocalConfigQuery.from_arguments,
		handler=query_local_config,
		parameters_schema={
			"type":"object",
			"properties":{
				"service_name":{"type":"string","description":"已登记的后端服务名称"},
				"environment":{"type":"string","enum":["production","staging"]},
				"at_time":{
					"type":"string",
					"description":"带时区的ISO 8601故障时刻，查询该时刻生效的配置；单个版本不代表整个故障窗口",
				},
			},
			"required":["service_name","environment","at_time"],
			"additionalProperties":False,
		},
	)
