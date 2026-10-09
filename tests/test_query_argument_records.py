import pytest
from fastapi.testclient import TestClient

from evidenceops.api import agent_app
from evidenceops.application.model_protocol import ToolCall
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.connectors.local_metric import build_local_metric_tool
from evidenceops.connectors.query_time import parse_query_time
from evidenceops.infrastructure.providers.mock_provider import MockProvider


def metric_arguments():
	return {
		"service_name":"order-service","environment":"production",
		"start_time":"2026-10-05T10:00:00+08:00","end_time":"2026-10-05T10:10:00+08:00","limit":50,
	}


def test_user_supplied_times_execute_without_changes()->None:
	runtime=ToolRuntime((build_local_metric_tool(),))
	arguments=metric_arguments()
	try:
		result=runtime.execute("query_service_metrics",arguments,"call-valid")
	finally:
		runtime.close()
	assert result.ok
	assert result.data["returned_count"]==3
	assert result.execution_record.query_arguments==arguments
	assert arguments["start_time"]=="2026-10-05T10:00:00+08:00"


@pytest.mark.parametrize("field",["start_time","end_time","at_time"])
@pytest.mark.parametrize("value",["not-a-date","2026-10-05T10:00:00",None])
def test_time_errors_identify_field(field,value)->None:
	with pytest.raises(ValueError,match=field):
		parse_query_time(value,field)


def test_invalid_model_time_is_visible_in_failed_http_response(monkeypatch)->None:
	arguments={**metric_arguments(),"end_time":"2026-10-05T10:10:00+08:0oops"}
	provider=MockProvider((ToolCall("call-bad-time","query_service_metrics",arguments),))
	monkeypatch.setattr(agent_app,"OpenAICompatibleProvider",lambda**kwargs:provider)
	with TestClient(agent_app.build_openai_agent_app("https://example.com/v1","test-key","test-model")) as client:
		response=client.post("/api/v1/agent/diagnosis",json={"description":"查询2026-10-05的指标"})
	body=response.json()
	assert response.status_code==503
	assert body["error_code"]=="INVALID_ARGUMENTS"
	assert "end_time时间格式无效" in body["error_detail"]["message"]
	record=body["execution_records"][1]
	assert record["query_arguments"]==arguments
	assert record["handler_started_at"] is None
	assert body["report"] is None


def test_record_excludes_unapproved_parameters()->None:
	runtime=ToolRuntime((build_local_metric_tool(),))
	arguments={**metric_arguments(),"api_key":"secret","path":"private-file","messages":["private"]}
	try:
		result=runtime.execute("query_service_metrics",arguments,"call-private")
	finally:
		runtime.close()
	assert not result.ok
	assert result.execution_record.query_arguments==metric_arguments()
