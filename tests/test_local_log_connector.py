import pytest

from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.connectors.local_log import LocalLogQuery,build_local_log_tool


@pytest.fixture
def runtime():
	runtime=ToolRuntime((build_local_log_tool(),))
	try:
		yield runtime
	finally:
		runtime.close()


def build_arguments()->dict:
	return {
		"service_name":"order-service",
		"environment":"production",
		"error_type":"rpc_timeout",
		"start_time":"2026-10-05T10:00:00+08:00",
		"end_time":"2026-10-05T10:10:00+08:00",
		"limit":50,
	}


def test_local_logs_returns_matching_records(runtime)->None:
	arguments=build_arguments()
	arguments["environment"]=" production "
	result=runtime.execute("query_service_logs",arguments)

	assert result.ok is True
	assert result.data["environment"]=="production"
	assert result.data["total_count"]==2
	assert result.data["returned_count"]==2
	assert result.data["truncated"] is False
	assert [match["line_number"] for match in result.data["matches"]]==[1,2]


def test_local_logs_rejects_unknown_environment(runtime)->None:
	arguments=build_arguments()
	arguments["environment"]="secret"
	result=runtime.execute("query_service_logs",arguments)

	assert result.ok is False
	assert result.error_code=="INVALID_ARGUMENTS"
	assert result.data is None


def test_local_logs_rejects_long_symptom(runtime)->None:
	arguments=build_arguments()
	arguments["symptom"]="故"*501
	result=runtime.execute("query_service_logs",arguments)

	assert result.ok is False
	assert result.error_code=="INVALID_ARGUMENTS"
	assert result.data is None


def test_local_logs_accepts_symptom_length_boundary()->None:
	arguments=build_arguments()
	arguments["symptom"]=" "+"故"*500+" "
	normalized=LocalLogQuery.from_arguments(arguments)

	assert normalized["symptom"]=="故"*500
	assert build_local_log_tool().parameters_schema["properties"]["symptom"]["maxLength"]==500


@pytest.mark.parametrize("service_name,environment",[("unknown-service","production"),("order-service","staging")])
def test_local_logs_rejects_unregistered_source(runtime,service_name,environment)->None:
	arguments=build_arguments()
	arguments["service_name"]=service_name
	arguments["environment"]=environment
	result=runtime.execute("query_service_logs",arguments)

	assert result.ok is False
	assert result.error_code=="UNKNOWN_SERVICE"
	assert result.data is None


def test_local_logs_queries_by_symptom_without_error_type(runtime)->None:
	arguments=build_arguments()
	del arguments["error_type"]
	arguments["symptom"]=" RPC timeout "
	result=runtime.execute("query_service_logs",arguments)

	assert result.ok is True
	assert result.data["returned_count"]==2
