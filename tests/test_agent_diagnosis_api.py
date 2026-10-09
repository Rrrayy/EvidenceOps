from fastapi.testclient import TestClient

from evidenceops.api import agent_app
from evidenceops.api.agent_app import build_agent_app
from evidenceops.application.model_protocol import ToolCall,ToolCallBatch,ModelProviderError,StructuredFinalAnswer
import pytest
from evidenceops.infrastructure.providers.mock_provider import MockProvider


def test_agent_api_runs_complete_mock_agent_flow()->None:
	with TestClient(build_agent_app()) as client:
		response=client.post("/api/v1/agent/diagnosis",json={"description":"分析order-service的RPC超时"})

	body=response.json()

	assert response.status_code==200
	assert body["status"]=="succeeded"
	assert body["error_code"] is None
	assert body["request_id"].startswith("req-")
	assert len(body["evidences"])==3
	assert [evidence["source"] for evidence in body["evidences"]]==["log","metric","config"]
	assert body["evidences"][2]["source_version"]=="local-config-jsonl-v1"
	assert "order-config-v1" in body["evidences"][2]["summary"]
	assert body["evidences"][1]["source_version"]=="local-metric-jsonl-v1"
	assert "匹配3条，返回3条" in body["evidences"][1]["summary"]
	assert body["report"] is not None
	assert body["report"]["run_id"]==body["run_id"]
	assert body["report"]["root_cause"]["evidence_ids"]==[
		body["evidences"][0]["evidence_id"],
		body["evidences"][1]["evidence_id"],
		body["evidences"][2]["evidence_id"],
	]
	assert body["report"]["recommendations"][0]["evidence_ids"]==body["report"]["root_cause"]["evidence_ids"]


def test_agent_api_rejects_blank_description()->None:
	with TestClient(build_agent_app()) as client:
		response=client.post("/api/v1/agent/diagnosis",json={"description":"   "})

	assert response.status_code==422


@pytest.mark.parametrize("failure",["model_timeout","invalid_draft"])
def test_failed_agent_api_preserves_execution_records(monkeypatch,failure)->None:
	def respond(request):
		if failure=="model_timeout":
			raise ModelProviderError("MODEL_TIMEOUT","模型超时")
		return StructuredFinalAnswer({"unexpected":True})
	provider=MockProvider((respond,))
	monkeypatch.setattr(agent_app,"OpenAICompatibleProvider",lambda**kwargs:provider)
	with TestClient(agent_app.build_openai_agent_app("https://example.com/v1","test-key","test-model")) as client:
		response=client.post("/api/v1/agent/diagnosis",json={"description":"排查超时"})
	body=response.json()
	assert response.status_code==503
	assert body["report"] is None
	assert len(body["execution_records"])==1
	record=body["execution_records"][0]
	assert record["run_id"]==body["run_id"]
	assert record["model_round"]==1
	assert record["model_request_id"]
	assert record["status"]==("failed" if failure=="model_timeout" else "succeeded")
	assert record["error_code"]==("MODEL_TIMEOUT" if failure=="model_timeout" else None)


def test_openai_app_registers_three_tools_for_runtime_and_model(monkeypatch)->None:
	requests=[]
	arguments={
		"service_name":"order-service",
		"environment":"production",
		"start_time":"2026-10-05T10:00:00+08:00",
		"end_time":"2026-10-05T10:10:00+08:00",
		"limit":50,
	}
	provider=MockProvider((
		ToolCallBatch((
		ToolCall("call-log-001","query_service_logs",{**arguments,"error_type":"rpc_timeout"}),
		ToolCall("call-metric-001","query_service_metrics",arguments),
		ToolCall("call-config-001","query_service_config",{
			"service_name":"order-service","environment":"production","at_time":"2026-10-05T10:02:00+08:00",
		}),
		)),
		agent_app.build_final_answer,
	))
	complete=provider.complete

	def record_request(request):
		requests.append(request)
		return complete(request)

	monkeypatch.setattr(provider,"complete",record_request)
	monkeypatch.setattr(agent_app,"OpenAICompatibleProvider",lambda**kwargs:provider)
	app=agent_app.build_openai_agent_app("https://example.com/v1","test-key","test-model")

	with TestClient(app) as client:
		response=client.post("/api/v1/agent/diagnosis",json={"description":"结合日志和指标分析RPC超时"})

	assert response.status_code==200
	assert len(response.json()["evidences"])==3
	assert len(requests)==2
	records=response.json()["execution_records"]
	assert len(records)==5
	assert [record["model_round"] for record in records if record["kind"]=="model"]==[1,2]
	assert all(record["run_id"]==response.json()["run_id"] for record in records)
	assert all(record["status"]=="succeeded" and record["duration_ms"]>=0 for record in records)
	for request in requests:
		assert {tool["function"]["name"] for tool in request.tools}=={"query_service_logs","query_service_metrics","query_service_config"}
		assert request.model=="test-model"
	assert [message["tool_call_id"] for message in requests[-1].messages if message["role"]=="tool"]==[
		"call-log-001","call-metric-001","call-config-001",
	]
