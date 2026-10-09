from fastapi.testclient import TestClient

from evidenceops.api.mock_diagnosis import create_app
from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator


class EmptyCollector:
	def collect(self,run):
		return ()


def test_mock_api_returns_evidence_report()->None:
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator(),lambda:"run-http-001")
	client=TestClient(create_app(service))
	response=client.post("/api/v1/mock/diagnosis",json={"description":"排查 C++ RPC 超时"})
	body=response.json()
	assert response.status_code==200
	assert body["status"]=="succeeded"
	assert body["run_id"]=="run-http-001"
	assert body["request_id"].startswith("req-")
	assert len(body["evidences"])==3
	assert body["report"] is not None


def test_mock_api_rejects_blank_description()->None:
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator())
	client=TestClient(create_app(service))
	response=client.post("/api/v1/mock/diagnosis",json={"description":"   "})
	assert response.status_code==422


def test_mock_api_returns_service_failure()->None:
	service=DiagnosisService(EmptyCollector(),MockRpcReportGenerator(),lambda:"run-http-002")
	client=TestClient(create_app(service))
	response=client.post("/api/v1/mock/diagnosis",json={"description":"排查 C++ RPC 超时"})
	body=response.json()
	assert response.status_code==503
	assert body["status"]=="failed"
	assert body["error_code"]=="EVIDENCE_INSUFFICIENT"
	assert body["evidences"]==[]
	assert body["report"] is None
