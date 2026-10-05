import json

from dataclasses import replace
from datetime import datetime
from hashlib import sha256

import pytest

from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.connectors.local_metric import build_local_metric_tool
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import EvidenceSource


@pytest.fixture
def metric_case():
	runtime=ToolRuntime((build_local_metric_tool(),))
	run=DiagnosisRun("run-metric-001","req-metric-001","分析订单服务RPC超时")
	collector=ToolEvidenceCollector(runtime,"order-service")
	arguments={
		"service_name":"order-service",
		"environment":"production",
		"start_time":"2026-10-05T10:00:00+08:00",
		"end_time":"2026-10-05T10:10:00+08:00",
		"limit":50,
	}
	try:
		yield runtime,run,collector,arguments
	finally:
		runtime.close()


def execute_metrics(runtime,run,arguments):
	result=runtime.execute("query_service_metrics",arguments,tool_call_id="call-metric-001")
	assert result.ok is True
	return replace(result,evidence_id=f"{run.run_id}-{result.tool_call_id}")


def test_metric_collector_converts_file_samples_without_reexecuting(metric_case,monkeypatch)->None:
	runtime,run,collector,arguments=metric_case
	result=execute_metrics(runtime,run,arguments)

	def reject_execute(*args,**kwargs):
		raise AssertionError("转换已有工具结果不应再次执行工具")

	monkeypatch.setattr(runtime,"execute",reject_execute)
	evidence=collector.collect_result(run,result)
	content=json.dumps(result.data,ensure_ascii=False,sort_keys=True,separators=(",",":"))

	assert evidence.evidence_id=="run-metric-001-call-metric-001"
	assert evidence.run_id==run.run_id
	assert evidence.source is EvidenceSource.METRIC
	assert evidence.observed_at==datetime.fromisoformat("2026-10-05T10:01:00+08:00")
	assert evidence.source_ref==f"{result.data['source_ref']}:lines:1-3"
	assert evidence.source_version=="local-metric-jsonl-v1"
	assert evidence.content_hash==sha256(content.encode("utf-8")).hexdigest()
	assert "匹配3条，返回3条，结果未截断" in evidence.summary
	assert "2026-10-05T10:03:00+08:00" in evidence.summary


def test_metric_collector_preserves_truncation_and_content_changes(metric_case)->None:
	runtime,run,collector,arguments=metric_case
	full_result=execute_metrics(runtime,run,arguments)
	full_evidence=collector.collect_result(run,full_result)
	arguments["limit"]=1
	result=execute_metrics(runtime,run,arguments)
	evidence=collector.collect_result(run,result)

	assert "匹配3条，返回1条，结果已截断" in evidence.summary
	assert evidence.source_ref.endswith(":lines:1-1")
	assert evidence.content_hash!=full_evidence.content_hash


def test_metric_collector_rejects_empty_query_without_inventing_time(metric_case)->None:
	runtime,run,collector,arguments=metric_case
	arguments["start_time"]="2026-10-05T11:00:00+08:00"
	arguments["end_time"]="2026-10-05T11:10:00+08:00"
	result=execute_metrics(runtime,run,arguments)
	assert result.data["samples"]==[]

	with pytest.raises(ToolCollectionError) as error_info:
		collector.collect_result(run,result)
	assert error_info.value.error_code=="NO_METRIC_SAMPLES"


@pytest.mark.parametrize("fault",[
	"wrong_count","wrong_truncation","wrong_service","wrong_environment",
	"outside_window","missing_timezone","invalid_metric","zero_capacity",
	"duplicate_line","wrong_order","missing_version",
])
def test_metric_collector_rejects_invalid_results(metric_case,fault)->None:
	runtime,run,collector,arguments=metric_case
	result=execute_metrics(runtime,run,arguments)
	data=result.data
	record=data["samples"][0]["record"]

	if fault=="wrong_count":
		data["returned_count"]=4
	elif fault=="wrong_truncation":
		data["truncated"]=True
	elif fault=="wrong_service":
		record["service_name"]="payment-service"
	elif fault=="wrong_environment":
		record["environment"]="staging"
	elif fault=="outside_window":
		record["timestamp"]="2026-10-01T10:01:00+08:00"
	elif fault=="missing_timezone":
		record["timestamp"]="2026-10-05T10:01:00"
	elif fault=="invalid_metric":
		record["active_threads"]=True
	elif fault=="zero_capacity":
		record["thread_limit"]=0
	elif fault=="duplicate_line":
		data["samples"][1]["line_number"]=1
	elif fault=="wrong_order":
		data["samples"].reverse()
	elif fault=="missing_version":
		data["source_version"]=""

	with pytest.raises(ToolCollectionError) as error_info:
		collector.collect_result(run,result)
	assert error_info.value.error_code=="INVALID_TOOL_RESULT"


def test_metric_collector_requires_existing_evidence_id(metric_case)->None:
	runtime,run,collector,arguments=metric_case
	result=replace(execute_metrics(runtime,run,arguments),evidence_id=None)

	with pytest.raises(ToolCollectionError) as error_info:
		collector.collect_result(run,result)
	assert error_info.value.error_code=="MISSING_EVIDENCE_ID"
