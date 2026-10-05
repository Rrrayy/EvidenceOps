import json

from dataclasses import replace
from datetime import datetime
from hashlib import sha256

import pytest

from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.connectors import local_config
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import EvidenceSource


@pytest.fixture
def config_case():
	runtime=ToolRuntime((local_config.build_local_config_tool(),))
	run=DiagnosisRun("run-config-001","req-config-001","分析RPC超时")
	arguments={"service_name":"order-service","environment":"production","at_time":"2026-10-05T10:02:00+08:00"}
	try:
		yield runtime,run,ToolEvidenceCollector(runtime,"order-service"),arguments
	finally:
		runtime.close()


@pytest.mark.parametrize("at_time,version,line_number",[
	("2026-10-05T10:02:00+08:00","order-config-v1",1),
	("2026-10-05T23:59:59+08:00","order-config-v1",1),
	("2026-10-06T00:00:00+08:00","order-config-v2",2),
	("2026-10-05T16:00:00+00:00","order-config-v2",2),
	("2026-11-01T00:00:00+08:00","order-config-v2",2),
])
def test_config_selects_historical_version(config_case,at_time,version,line_number)->None:
	runtime,_,_,arguments=config_case
	result=runtime.execute("query_service_config",{**arguments,"at_time":at_time})
	assert result.ok
	assert result.data["config"]["record"]["config_version"]==version
	assert result.data["config"]["line_number"]==line_number


@pytest.mark.parametrize("changes,code",[
	({"at_time":"2026-10-05T10:02:00"},"INVALID_ARGUMENTS"),
	({"environment":"unknown"},"INVALID_ARGUMENTS"),
	({"path":"other.jsonl"},"INVALID_ARGUMENTS"),
	({"service_name":"unknown-service"},"UNKNOWN_SERVICE"),
	({"at_time":"2026-09-30T00:00:00+08:00"},"TOOL_EXECUTION_FAILED"),
])
def test_config_rejects_invalid_or_unavailable_queries(config_case,changes,code)->None:
	runtime,_,_,arguments=config_case
	result=runtime.execute("query_service_config",{**arguments,**changes})
	assert not result.ok
	assert result.data is None
	assert result.error_code==code


@pytest.mark.parametrize("fault",["overlap","duplicate_version","invalid_interval","boolean_capacity","zero_timeout","missing_end"])
def test_config_rejects_corrupt_or_ambiguous_source(config_case,tmp_path,monkeypatch,fault)->None:
	runtime,_,_,arguments=config_case
	key=("order-service","production")
	source=local_config.CONFIG_REGISTRY[key]
	records=[json.loads(line) for line in source.source_path.read_text(encoding="utf-8").splitlines()]
	if fault=="overlap":
		records[1]["effective_from"]="2026-10-05T00:00:00+08:00"
	elif fault=="duplicate_version":
		records[1]["config_version"]=records[0]["config_version"]
	elif fault=="invalid_interval":
		records[0]["effective_until"]=records[0]["effective_from"]
	elif fault=="boolean_capacity":
		records[0]["thread_pool_size"]=True
	elif fault=="zero_timeout":
		records[0]["rpc_timeout_ms"]=0
	else:
		del records[0]["effective_until"]
	path=tmp_path/"config.jsonl"
	path.write_text("\n".join(json.dumps(record) for record in records),encoding="utf-8")
	monkeypatch.setitem(local_config.CONFIG_REGISTRY,key,replace(source,source_path=path))
	result=runtime.execute("query_service_config",arguments)
	assert not result.ok
	assert result.error_code=="TOOL_EXECUTION_FAILED"
	assert result.data is None
	if fault=="overlap":
		assert "多个生效配置" in result.error_message


def execute_config(runtime,run,arguments):
	result=runtime.execute("query_service_config",arguments,tool_call_id="call-config-001")
	assert result.ok
	return replace(result,evidence_id=f"{run.run_id}-{result.tool_call_id}")


def test_config_evidence_preserves_identity_version_and_content(config_case,monkeypatch)->None:
	runtime,run,collector,arguments=config_case
	result=execute_config(runtime,run,arguments)
	def reject_execute(*args,**kwargs):
		raise AssertionError("转换结果不应重复执行工具")
	monkeypatch.setattr(runtime,"execute",reject_execute)
	evidence=collector.collect_result(run,result)
	content=json.dumps(result.data,ensure_ascii=False,sort_keys=True,separators=(",",":"))
	assert evidence.source is EvidenceSource.CONFIG
	assert evidence.run_id==run.run_id
	assert evidence.evidence_id==result.evidence_id
	assert evidence.observed_at==datetime.fromisoformat("2026-10-01T00:00:00+08:00")
	assert evidence.source_ref==f"{result.data['source_ref']}:line:1"
	assert evidence.source_version=="local-config-jsonl-v1"
	assert evidence.content_hash==sha256(content.encode("utf-8")).hexdigest()
	assert "order-config-v1" in evidence.summary
	assert "最多额外重试2次" in evidence.summary


@pytest.mark.parametrize("fault",["wrong_service","inactive_version","boolean_retries","missing_end","missing_id"])
def test_config_collector_rejects_invalid_evidence(config_case,fault)->None:
	runtime,run,collector,arguments=config_case
	result=execute_config(runtime,run,arguments)
	record=result.data["config"]["record"]
	if fault=="wrong_service":
		record["service_name"]="payment-service"
	elif fault=="inactive_version":
		result.data["at_time"]="2026-10-06T00:00:00+08:00"
	elif fault=="boolean_retries":
		record["max_retries"]=True
	elif fault=="missing_end":
		del record["effective_until"]
	else:
		result=replace(result,evidence_id=None)
	with pytest.raises(ToolCollectionError) as error_info:
		collector.collect_result(run,result)
	assert error_info.value.error_code==("MISSING_EVIDENCE_ID" if fault=="missing_id" else "INVALID_TOOL_RESULT")
