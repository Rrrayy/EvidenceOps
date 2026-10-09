from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel,field_validator
from starlette.responses import JSONResponse

from evidenceops.application.agent_diagnosis_factory import AgentDiagnosisAssembly
from evidenceops.application.diagnosis_response import to_response
from evidenceops.application.diagnosis_history import load_diagnosis_history
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

		result=assembly.diagnosis_service.execute(request_id,request.description)

		response=to_response(result)

		status_code=(200 if result.run.status is RunStatus.SUCCEEDED else 503)

		return JSONResponse(status_code=status_code,content=response)

	@app.get("/api/v1/agent/runs/{run_id}")
	def get_diagnosis(run_id:str)->JSONResponse:
		# 复制 ID 时的首尾空白不属于身份，先规范化再查询。
		run_id=run_id.strip()

		if assembly.diagnosis_persistence is None:
			return JSONResponse(
				status_code=503,
				content={
					"error_code":"PERSISTENCE_DISABLED",
					"message":"当前未启用PostgreSQL持久化",
				},
			)

		try:
			history=load_diagnosis_history(assembly.diagnosis_persistence,run_id)
		except ValueError as error:
			return JSONResponse(status_code=422,content={"error_code":"INVALID_ARGUMENTS","message":str(error)})

		if history is None:
			return JSONResponse(status_code=404,content={"error_code":"RUN_NOT_FOUND","message":"诊断运行不存在"})

		return JSONResponse(status_code=200,content=_history_response(history))

	return app


def _history_response(history)->dict:
	run=history.run
	return {
		"run_id":run.run_id,
		"request_id":run.request_id,
		"status":run.status.value,
		"error_code":run.error_code,
		"created_at":run.created_at.isoformat(),
		"started_at":run.started_at.isoformat() if run.started_at else None,
		"finished_at":run.finished_at.isoformat() if run.finished_at else None,
		"evidences":[{
			"evidence_id":item.evidence_id,
			"run_id":item.run_id,
			"source":item.source,
			"observed_at":item.observed_at.isoformat(),
			"summary":item.summary,
			"source_ref":item.source_ref,
			"content_hash":item.content_hash,
			"source_version":item.source_version,
		} for item in history.evidences],
		"report":_report_response(history.report),
		"execution_records":[_execution_response(item) for item in history.execution_records],
	}


def _report_response(report):
	if report is None:
		return None

	return {
		"run_id":report.run_id,
		"root_cause":{
			"text":report.root_cause.text,
			"evidence_ids":list(report.root_cause.evidence_ids),
		},
		"recommendations":[{
			"text":claim.text,
			"evidence_ids":list(claim.evidence_ids),
		} for claim in report.recommendations],
		"confidence":report.confidence,
		"limitations":report.limitations,
	}


def _execution_response(record):
	return {
		"kind":record.kind,
		"run_id":record.run_id,
		"model_round":record.model_round,
		"model_request_id":record.model_request_id,
		"tool_name":record.tool_name,
		"tool_call_id":record.tool_call_id,
		"query_arguments":record.query_arguments,
		"started_at":record.started_at.isoformat(),
		"finished_at":record.finished_at.isoformat(),
		"duration_ms":record.duration_ms,
		"status":record.status,
		"error_code":record.error_code,
		"handler_started_at":record.handler_started_at.isoformat() if record.handler_started_at else None,
		"handler_finished_at":record.handler_finished_at.isoformat() if record.handler_finished_at else None,
	}
