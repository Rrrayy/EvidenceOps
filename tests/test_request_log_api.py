from hashlib import sha256

from fastapi.testclient import TestClient

from evidenceops.api.mock_diagnosis import app


def test_request_log_produces_evidence_from_submitted_line()->None:
	raw_line="2026-10-01T10:00:00+08:00 RPC timeout active_threads=64 thread_limit=64 pending_tasks=128"
	client=TestClient(app)
	response=client.post("/api/v1/mock/log-diagnosis",json={"description":"排查 RPC 超时","log_text":raw_line})
	body=response.json()
	assert response.status_code==200
	assert body["status"]=="succeeded"
	assert len(body["evidences"])==1
	assert body["evidences"][0]["content_hash"]==sha256(raw_line.encode("utf-8")).hexdigest()
	assert body["evidences"][0]["observed_at"]=="2026-10-01T10:00:00+08:00"
	assert body["report"]["root_cause"]["evidence_ids"]==[body["evidences"][0]["evidence_id"]]


def test_unmatched_log_does_not_receive_fixed_diagnosis()->None:
	client=TestClient(app)
	response=client.post("/api/v1/mock/log-diagnosis",json={"description":"排查 RPC 超时",
		"log_text":"2026-10-01T10:00:00+08:00 RPC timeout active_threads=2 thread_limit=64 pending_tasks=0"})
	body=response.json()
	assert response.status_code==503
	assert body["error_code"]=="EVIDENCE_INSUFFICIENT"
	assert body["evidences"]==[]
	assert body["report"] is None
