from contextlib import asynccontextmanager
import asyncio
from uuid import uuid4

from fastapi import FastAPI,Header,Query
from dataclasses import asdict
from starlette.background import BackgroundTask
from pydantic import BaseModel,field_validator
from starlette.responses import JSONResponse,StreamingResponse
from evidenceops.api.diagnosis_stream import DiagnosisStreamRunner,StreamBusyError

from evidenceops.application.agent_diagnosis_factory import AgentDiagnosisAssembly
from evidenceops.application.diagnosis_response import to_response
from evidenceops.application.diagnosis_history import load_diagnosis_history
from evidenceops.domain.diagnosis_run import RunStatus
from evidenceops.application.run_repository import RunPersistenceError
from evidenceops.application.event_history import EventHistoryError,load_event_page,parse_event_cursor
from evidenceops.api.event_replay import EventReplay,ReplayBusyError


class AgentDiagnosisRequest(BaseModel):
	description:str

	@field_validator("description")
	@classmethod
	def validate_description(cls,description:str)->str:
		if not description.strip():
			raise ValueError("description不能为空")

		return description.strip()


def create_app(assembly:AgentDiagnosisAssembly)->FastAPI:
	stream_runner=DiagnosisStreamRunner(assembly.diagnosis_service)
	replay=EventReplay(assembly.diagnosis_persistence)
	@asynccontextmanager
	async def lifespan(_:FastAPI):
		try:
			yield
		finally:
			await asyncio.to_thread(stream_runner.close)
			assembly.close()

	app=FastAPI(lifespan=lifespan)

	def event_error(error):
		if isinstance(error,EventHistoryError):
			return JSONResponse(status_code=error.status_code,content={"error_code":error.error_code,"message":str(error)})
		return JSONResponse(status_code=503,content={"error_code":"PERSISTENCE_FAILED","message":"事件读取失败"})

	@app.get("/api/v1/agent/runs/{run_id}/events")
	def get_events(run_id:str,after:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=1000)):
		try:
			page=load_event_page(assembly.diagnosis_persistence,run_id,after,limit)
		except Exception as error:
			return event_error(error)
		return JSONResponse(content=asdict(page))

	@app.get("/api/v1/agent/runs/{run_id}/events/stream",response_class=StreamingResponse,
		responses={200:{"content":{"text/event-stream":{}}},429:{"description":"观察连接已达上限"}})
	async def replay_events(run_id:str,after:int|None=Query(None,ge=0),last_event_id:str|None=Header(None)):
		lease=None
		try:
			run_id=run_id.strip()
			cursor=parse_event_cursor(run_id,after,last_event_id)
			lease=replay.reserve()
			page=await asyncio.to_thread(load_event_page,assembly.diagnosis_persistence,run_id,cursor,replay.page_size)
		except ReplayBusyError as error:
			return JSONResponse(status_code=429,content={"error_code":"REPLAY_BUSY","message":str(error)})
		except BaseException as error:
			if lease is not None:
				lease.close()
			if not isinstance(error,Exception):
				raise
			return event_error(error)
		return StreamingResponse(lease.stream(page),media_type="text/event-stream",
			headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"},background=BackgroundTask(lease.close))

	@app.post("/api/v1/agent/runs/{run_id}/cancel")
	async def cancel_diagnosis(run_id:str)->JSONResponse:
		run_id=run_id.strip()
		if not run_id:
			return JSONResponse(status_code=422,content={"error_code":"INVALID_ARGUMENTS","message":"run_id不能为空"})
		try:
			# 取消请求事件现在需要数据库提交；同步IO不能阻塞ASGI事件循环。
			decision=await asyncio.to_thread(assembly.diagnosis_service.request_cancel,run_id)
		except RunPersistenceError:
			return JSONResponse(status_code=503,content={"run_id":run_id,"error_code":"PERSISTENCE_FAILED",
				"message":"取消事件保存失败，请查询历史状态"})
		if decision is not None:
			return JSONResponse(status_code=202 if decision["cancellation_requested"] else 409,content=decision)
		if assembly.diagnosis_persistence is not None:
			# 活跃Run取消仅操作内存；历史回查的同步数据库IO移出事件循环。
			history=await asyncio.to_thread(load_diagnosis_history,assembly.diagnosis_persistence,run_id)
			if history is not None:
				if history.run.status in (RunStatus.SUCCEEDED,RunStatus.FAILED,RunStatus.CANCELLED):
					return JSONResponse(status_code=200,content={"run_id":run_id,"status":history.run.status.value,
						"cancellation_requested":False})
				return JSONResponse(status_code=409,content={"run_id":run_id,"error_code":"RUN_NOT_ACTIVE",
					"message":"当前进程未执行该Run；取消请求未被接纳"})
		return JSONResponse(status_code=404,content={"error_code":"RUN_NOT_FOUND","message":"诊断运行不存在"})

	@app.post("/api/v1/agent/diagnosis/stream",response_class=StreamingResponse,
		responses={200:{"content":{"text/event-stream":{}}},429:{"description":"流式诊断并发已达上限"}})
	async def diagnose_stream(request:AgentDiagnosisRequest):
		try:
			channel=stream_runner.start(request.description)
		except StreamBusyError as error:
			return JSONResponse(status_code=429,content={"error_code":"STREAM_BUSY","message":str(error)})
		return StreamingResponse(channel.stream(),media_type="text/event-stream",
			headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

	@app.post("/api/v1/agent/diagnosis")
	def diagnose(request:AgentDiagnosisRequest)->JSONResponse:
		request_id=f"req-{uuid4()}"

		try:
			result=assembly.diagnosis_service.execute(request_id,request.description)
		except RunPersistenceError as error:
			return JSONResponse(status_code=503,content={"run_id":error.run_id,"request_id":request_id,
				"error_code":"PERSISTENCE_FAILED","message":"诊断数据保存失败，请查询历史状态"})

		response=to_response(result)

		status_code=(200 if result.run.status in (RunStatus.SUCCEEDED,RunStatus.CANCELLED) else 503)

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
