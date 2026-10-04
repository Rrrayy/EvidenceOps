from fastapi.testclient import TestClient

from evidenceops.api.agent_app import build_agent_app


def test_agent_api_runs_complete_mock_agent_flow()->None:
	client=TestClient(build_agent_app())

	response=client.post(
		"/api/v1/agent/diagnosis",
		json={
			"description":"分析order-service的RPC超时",
		},
	)

	body=response.json()

	assert response.status_code==200
	assert body["status"]=="succeeded"
	assert body["error_code"] is None
	assert body["request_id"].startswith("req-")
	assert len(body["evidences"])==1
	assert body["report"] is not None
	assert body["report"]["run_id"]==body["run_id"]
	assert body["report"]["root_cause"]["evidence_ids"]==[
		body["evidences"][0]["evidence_id"],
	]


def test_agent_api_rejects_blank_description()->None:
	client=TestClient(build_agent_app())

	response=client.post(
		"/api/v1/agent/diagnosis",
		json={
			"description":"   ",
		},
	)

	assert response.status_code==422