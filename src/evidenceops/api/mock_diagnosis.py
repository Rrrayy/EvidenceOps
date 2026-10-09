from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel,field_validator
from starlette.responses import JSONResponse
from pydantic import Field

from evidenceops.mocks.request_log import RequestLogEvidenceCollector,RequestLogReportGenerator
from evidenceops.application.diagnosis_response import to_response
from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.domain.diagnosis_run import RunStatus
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator


class MockDiagnosisRequest(BaseModel):
	description:str

	@field_validator("description")
	@classmethod
	def validate_description(cls,description:str)->str:
		if not description.strip():
			raise ValueError("description不能为空")
		return description.strip()

class RequestLogDiagnosisRequest(BaseModel):
	description:str
	log_text:str=Field(max_length=20000)

	@field_validator("description","log_text")
	@classmethod
	def validate_nonblank(cls,value:str)->str:
		if not value.strip():
			raise ValueError("输入不能为空")
		return value

def create_app(service:DiagnosisService)->FastAPI:
	app=FastAPI()

	@app.post("/api/v1/mock/diagnosis")
	def diagnose(request:MockDiagnosisRequest)->JSONResponse:
		request_id=f"req-{uuid4()}"
		result=service.execute(request_id,request.description)
		response=to_response(result)
		status_code=200 if result.run.status is RunStatus.SUCCEEDED else 503
		return JSONResponse(status_code=status_code,content=response)

	@app.post("/api/v1/mock/log-diagnosis")
	def diagnose_request_log(request:RequestLogDiagnosisRequest)->JSONResponse:
		collector=RequestLogEvidenceCollector(request.log_text)
		service_for_request=DiagnosisService(collector,RequestLogReportGenerator())
		request_id=f"req-{uuid4()}"
		result=service_for_request.execute(request_id,request.description)
		response=to_response(result)
		status_code=200 if result.run.status is RunStatus.SUCCEEDED else 503
		return JSONResponse(status_code=status_code,content=response)
	return app


app=create_app(DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator()))
