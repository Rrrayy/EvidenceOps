import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.application.agent_collection_result import AgentCollectionError
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.agent_loop import AgentLoopResult
from evidenceops.application.model_protocol import ModelProviderError,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.run_budget import RunBudget
from evidenceops.application.diagnosis_service import DiagnosisService
from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.application.tool_runtime import ToolResult
from evidenceops.connectors.local_config import build_local_config_tool
from evidenceops.connectors.local_log import build_local_log_tool
from evidenceops.connectors.local_metric import build_local_metric_tool
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.models import Base
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def protocol_failure(request):
	raise ModelProviderError("MODEL_PROTOCOL_ERROR","模拟第二轮协议解析失败")


@pytest.mark.parametrize("final_response",[protocol_failure,StructuredFinalAnswer({"unexpected":True})])
def test_failed_run_preserves_three_evidences_in_sse_and_database(final_response):
	# 使用真实SQLAlchemy仓储和事务；SQLite仅用于确定性回归，不代替PostgreSQL验收。
	engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
	Base.metadata.create_all(engine)
	persistence=SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)
	window={"service_name":"order-service","environment":"production",
		"start_time":"2026-10-05T10:00:00+08:00","end_time":"2026-10-05T10:10:00+08:00","limit":50}
	calls=ToolCallBatch((ToolCall("log","query_service_logs",dict(window,error_type="rpc_timeout")),
		ToolCall("metric","query_service_metrics",window),ToolCall("config","query_service_config",
			{"service_name":"order-service","environment":"production","at_time":"2026-10-05T10:02:00+08:00"})))
	assembly=build_agent_diagnosis_assembly(MockProvider((calls,final_response)),"mock",
		(build_local_log_tool(),build_local_metric_tool(),build_local_config_tool()),"order-service",
		diagnosis_persistence=persistence)
	with TestClient(create_app(assembly)) as client:
		stream=client.post("/api/v1/agent/diagnosis/stream",json={"description":"失败证据归档"})
		events=[json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
		assert events[-1]["event"]=="run_failed"
		result=events[-1]["data"]["result"]
		history=client.get(f"/api/v1/agent/runs/{result['run_id']}").json()
		for body in (result,history):
			assert body["status"]=="failed" and body["error_code"]=="MODEL_PROTOCOL_ERROR"
			assert body["report"] is None
			assert sorted(item["source"] for item in body["evidences"])==["config","log","metric"]
			assert len(body["execution_records"])==5
			assert sum(item["kind"]=="tool" and item["status"]=="succeeded" for item in body["execution_records"])==3
		# SQLite不保留时区且仓储按观测时间排序，比较归档身份与内容而非数组位置。
		fields=("evidence_id","source","summary","source_ref","content_hash","source_version")
		assert {tuple(item[field] for field in fields) for item in history["evidences"]}=={
			tuple(item[field] for field in fields) for item in result["evidences"]}


@pytest.mark.parametrize("loop_error",[None,"RUN_TIMEOUT","MODEL_PROTOCOL_ERROR"])
def test_partial_conversion_preserves_valid_results_and_original_loop_error(loop_error):
	assembly=build_agent_diagnosis_assembly(MockProvider((StructuredFinalAnswer({"unused":True}),)),"mock",
		(build_thread_pool_tool(),),"order-service")
	run=DiagnosisRun("run-partial","req-partial","部分转换失败")
	spec=build_thread_pool_tool()
	valid=ToolResult(spec.name,True,data=spec.handler({"service_name":"order-service"}),evidence_id="ev-first")
	broken=replace(valid,data={},evidence_id="ev-broken")
	last=replace(valid,evidence_id="ev-last")
	failed=ToolResult(spec.name,False,error_code="TOOL_TIMEOUT")
	loop_result=AgentLoopResult(None,(valid,broken,failed,last),loop_error)
	assembly.evidence_collector._agent_loop.run=lambda *args,**kwargs:loop_result
	try:
		with pytest.raises(AgentCollectionError if loop_error else ToolCollectionError) as captured:
			assembly.evidence_collector.collect(run)
		assert [item.evidence_id for item in captured.value.evidences]==["ev-first","ev-last"]
		assert captured.value.error_code==(loop_error or "INVALID_TOOL_RESULT")
	finally:
		assembly.close()


def test_expired_budget_still_archives_completed_observation():
	assembly=build_agent_diagnosis_assembly(MockProvider((StructuredFinalAnswer({"unused":True}),)),"mock",
		(build_thread_pool_tool(),),"order-service")
	run=DiagnosisRun("run-expired","req-expired","预算失败")
	spec=build_thread_pool_tool()
	result=ToolResult(spec.name,True,data=spec.handler({"service_name":"order-service"}),evidence_id="ev-observed")
	assembly.evidence_collector._agent_loop.run=lambda *args,**kwargs:AgentLoopResult(None,(result,),None)
	budget=RunBudget(1,lambda:0)
	budget._clock=lambda:2
	try:
		with pytest.raises(AgentCollectionError) as captured:
			assembly.evidence_collector.collect(run,budget=budget)
		assert captured.value.error_code=="RUN_TIMEOUT"
		assert len(captured.value.evidences)==1
	finally:
		assembly.close()


def test_service_persists_partial_conversion_failure(monkeypatch):
	assembly=build_agent_diagnosis_assembly(MockProvider((StructuredFinalAnswer({"unused":True}),)),"mock",
		(build_thread_pool_tool(),),"order-service")
	spec=build_thread_pool_tool()
	valid=ToolResult(spec.name,True,data=spec.handler({"service_name":"order-service"}),evidence_id="ev-good")
	broken=replace(valid,data={},evidence_id="ev-bad")
	assembly.evidence_collector._agent_loop.run=lambda *args,**kwargs:AgentLoopResult(None,(valid,broken),None)
	saved=[]
	monkeypatch.setattr(assembly.diagnosis_service,"_persist_failure",lambda run,evidences,records:saved.append(evidences))
	try:
		result=assembly.diagnosis_service.execute("req-conversion","转换失败")
		assert result.run.error_code=="EVIDENCE_COLLECTION_FAILED"
		assert result.error_detail["code"]=="INVALID_TOOL_RESULT"
		assert result.report is None and len(result.evidences)==1
		assert saved==[result.evidences]
	finally:
		assembly.close()


def test_failure_evidences_are_checked_for_run_ownership_and_duplicates():
	assembly=build_agent_diagnosis_assembly(MockProvider((StructuredFinalAnswer({"unused":True}),)),"mock",
		(build_thread_pool_tool(),),"order-service")
	run=DiagnosisRun("run-owner","req-owner","归属检查")
	spec=build_thread_pool_tool()
	result=ToolResult(spec.name,True,data=spec.handler({"service_name":"order-service"}),evidence_id="ev-owned")
	try:
		evidence=assembly.evidence_collector._tool_collector.collect_result(run,result)
		foreign=replace(evidence,run_id="run-other")
		assert DiagnosisService._failure_evidences(run,(foreign,evidence,evidence,"invalid"))==(evidence,)
	finally:
		assembly.close()
