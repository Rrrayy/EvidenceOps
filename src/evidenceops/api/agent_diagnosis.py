from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel,field_validator
from starlette.responses import JSONResponse

from evidenceops.application.agent_diagnosis_factory import AgentDiagnosisAssembly
from evidenceops.application.diagnosis_response import to_response
from evidenceops.domain.diagnosis_run import RunStatus


class AgentDiagnosisRequest(BaseModel):
	description:str

	@field_validator("description")
	@classmethod
	def validate_description(cls,description:str)->str:
		if not description.strip():
			raise ValueError("description不能为空")

		return description.strip()


def create_app(assembly:AgentDiagnosisAssembly)->FastAPI:
	@asynccontextmanager
	async def lifespan(_:FastAPI):
		yield
		assembly.close()

	app=FastAPI(lifespan=lifespan)

	@app.post("/api/v1/agent/diagnosis")
	def diagnose(request:AgentDiagnosisRequest)->JSONResponse:
		request_id=f"req-{uuid4()}"

		result=assembly.diagnosis_service.execute(
			request_id,
			request.description,
		)

		response=to_response(result)

		status_code=(
			200
			if result.run.status is RunStatus.SUCCEEDED
			else 503
		)

		return JSONResponse(
			status_code=status_code,
			content=response,
		)

	return app