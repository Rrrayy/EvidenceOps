"""负责诊断 HTTP 接口、运行历史查询及模型连接管理的接入。"""
from contextlib import asynccontextmanager
import asyncio
import logging
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
from evidenceops.application.history_response import history_response as _history_response
from evidenceops.application.run_recovery import recover_interrupted_runs
from evidenceops.domain.diagnosis_run import RunStatus
from evidenceops.application.run_repository import RunPersistenceError
from evidenceops.application.event_history import EventHistoryError,load_event_page,parse_event_cursor
from evidenceops.api.event_replay import EventReplay,ReplayBusyError
from evidenceops.infrastructure.providers.mock_provider import MockProvider


class AgentDiagnosisRequest(BaseModel):
	description:str
	connection_id:str|None=None
	model_id:str|None=None
	expected_version:int|None=None

	@field_validator("description")
	@classmethod
	def validate_description(cls,description:str)->str:
		if not description.strip():
			raise ValueError("description不能为空")
		if len(description)>100000:
			raise ValueError("故障描述不能超过100000字符")
		if not any(character.isalpha() or character.isdecimal() for character in description):
			raise ValueError("请补充故障现象、错误信息或日志，不能只输入标点或符号")

		return description.strip()


def create_app(assembly:AgentDiagnosisAssembly,connection_manager=None)->FastAPI:
	stream_runner=DiagnosisStreamRunner(assembly.diagnosis_service)
	replay=EventReplay(assembly.diagnosis_persistence)
	@asynccontextmanager
	async def lifespan(_:FastAPI):
		try:
			if assembly.diagnosis_persistence is not None:
				await asyncio.to_thread(assembly.diagnosis_persistence.acquire_instance_lock)
				app.state.recovered_runs=await asyncio.to_thread(recover_interrupted_runs,assembly.diagnosis_persistence)
				logging.getLogger(__name__).info("Startup recovered %s interrupted runs",app.state.recovered_runs)
			yield
		finally:
			try:
				await asyncio.to_thread(stream_runner.close)
			finally:
				await asyncio.to_thread(assembly.close)

	app=FastAPI(lifespan=lifespan)
	app.state.assembly=assembly
	app.state.connection_manager=connection_manager
	if connection_manager is not None:
		from evidenceops.api.model_connections import install_routes
		install_routes(app,connection_manager)

	@app.get("/api/v1/agent/capabilities")
	def get_capabilities():

		return {"persistence":assembly.diagnosis_persistence is not None,"input":"description","sources":["log","metric","config"],
			"model_connections":connection_manager is not None,"provider_mode":"mock" if isinstance(assembly.provider,MockProvider) else "configured"}

	@app.get("/api/v1/agent/runs")
	def list_runs(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0,le=100000),status:RunStatus|None=None,search:str=Query("",max_length=200)):

		if assembly.diagnosis_persistence is None:
			return JSONResponse(status_code=503,content={"error_code":"PERSISTENCE_DISABLED","message":"当前未启用PostgreSQL持久化，无法查询历史"})
		try:

			with assembly.diagnosis_persistence.transaction() as transaction:
				rows=transaction.run.list_recent(limit+1,offset,status.value if status else None,search.strip())
			items=[{"run_id":row.run_id,"description":row.description,"status":row.status.value,"error_code":row.error_code,
				"created_at":row.created_at.isoformat(),"started_at":row.started_at.isoformat() if row.started_at else None,
				"finished_at":row.finished_at.isoformat() if row.finished_at else None} for row in rows[:limit]]
			return {"items":items,"offset":offset,"limit":limit,"has_more":len(rows)>limit}
		except Exception:
			return JSONResponse(status_code=503,content={"error_code":"PERSISTENCE_FAILED","message":"历史读取失败，请稍后重试"})

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

			decision=await asyncio.to_thread((connection_manager.running.get(run_id,assembly.diagnosis_service) if connection_manager else assembly.diagnosis_service).request_cancel,run_id)
		except RunPersistenceError:
			return JSONResponse(status_code=503,content={"run_id":run_id,"error_code":"PERSISTENCE_FAILED",
				"message":"取消事件保存失败，请查询历史状态"})
		if decision is not None:
			return JSONResponse(status_code=202 if decision["cancellation_requested"] else 409,content=decision)
		if assembly.diagnosis_persistence is not None:

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
			selected=await asyncio.to_thread(connection_manager.choose,request.connection_id,request.model_id,request.expected_version) if connection_manager else None
			try:
				channel=stream_runner.start(request.description,selected) if selected else stream_runner.start(request.description)
			except Exception:
				if selected: selected.release()
				raise
		except StreamBusyError as error:
			return JSONResponse(status_code=429,content={"error_code":"STREAM_BUSY","message":str(error)})
		return StreamingResponse(channel.stream(),media_type="text/event-stream",
			headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

	@app.post("/api/v1/agent/diagnosis")
	def diagnose(request:AgentDiagnosisRequest)->JSONResponse:
		request_id=f"req-{uuid4()}"

		try:
			selected=connection_manager.choose(request.connection_id,request.model_id,request.expected_version) if connection_manager else assembly.diagnosis_service
			result=selected.execute(request_id,request.description)
		except RunPersistenceError as error:
			return JSONResponse(status_code=503,content={"run_id":error.run_id,"request_id":request_id,
				"error_code":"PERSISTENCE_FAILED","message":"诊断数据保存失败，请查询历史状态"})

		response=to_response(result)

		status_code=(200 if result.run.status in (RunStatus.SUCCEEDED,RunStatus.CANCELLED) else 503)

		return JSONResponse(status_code=status_code,content=response)

	@app.get("/api/v1/agent/runs/{run_id}")
	def get_diagnosis(run_id:str)->JSONResponse:

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
		except Exception:
			return JSONResponse(status_code=503,content={"error_code":"PERSISTENCE_FAILED","message":"诊断档案读取失败，请稍后重试"})

		if history is None:
			return JSONResponse(status_code=404,content={"error_code":"RUN_NOT_FOUND","message":"诊断运行不存在"})

		response=_history_response(history)
		if not response["model_config"] and connection_manager: response["model_config"]=connection_manager.store.snapshot(run_id)
		return JSONResponse(status_code=200,content=response)

	return app
