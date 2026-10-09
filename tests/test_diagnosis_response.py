import json

from evidenceops.application.diagnosis_response import to_response
from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator
from evidenceops.application.diagnosis_service import DiagnosisExecution

class EmptyCollector:
	def collect(self,run):
		return ()


def test_success_response_is_json_serializable()->None:
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator(),lambda:"run-response-001")
	result=service.execute("req-response-001","排查 C++ RPC 超时")
	response=to_response(result)
	json.dumps(response)
	assert response["status"]=="succeeded"
	assert response["error_code"] is None
	assert len(response["evidences"])==3
	assert response["report"] is not None
	assert len(response["report"]["root_cause"]["evidence_ids"])==3


def test_failed_response_keeps_one_structure()->None:
	service=DiagnosisService(EmptyCollector(),MockRpcReportGenerator(),lambda:"run-response-002")
	result=service.execute("req-response-002","排查 C++ RPC 超时")
	response=to_response(result)
	json.dumps(response)
	assert response["status"]=="failed"
	assert response["error_code"]=="EVIDENCE_INSUFFICIENT"
	assert response["evidences"]==[]
	assert response["report"] is None


def test_response_keeps_tool_error_detail()->None:
	service=DiagnosisService(EmptyCollector(),MockRpcReportGenerator(),lambda:"run-response-003")
	result=service.execute("req-response-003","排查 RPC 超时")

	result=DiagnosisExecution(
		run=result.run,
		evidences=result.evidences,
		report=None,
		error_detail={
			"code":"TOOL_TIMEOUT",
			"message":"工具执行超过时间限制",
		},
	)

	response=to_response(result)

	assert response["error_code"]=="EVIDENCE_INSUFFICIENT"
	assert response["error_detail"]=={"code":"TOOL_TIMEOUT","message":"工具执行超过时间限制",}
	assert response["report"] is None
