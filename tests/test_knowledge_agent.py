import json
import os
from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema,DropSchema
from sqlalchemy.orm import sessionmaker

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.diagnosis_history import load_diagnosis_history
from evidenceops.application.diagnosis_response import to_response
from evidenceops.application.history_response import history_response
from evidenceops.application.knowledge_retrieval import KeywordKnowledgeRetriever
from evidenceops.application.knowledge_splitter import KnowledgeSplitter
from evidenceops.application.hybrid_knowledge import fuse_rankings
from evidenceops.application.bm25_knowledge import bm25_ranking
from evidenceops.application.model_protocol import ModelProviderError,StructuredFinalAnswer,ToolCall,ToolCallBatch
from evidenceops.application.run_control import RunControl
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.connectors.knowledge_search import build_knowledge_search_tool
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.models import Base
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.database.vector_repository import VectorRepository
from evidenceops.infrastructure.knowledge_tools import configured_knowledge_tools
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,KnowledgeDocument,SplitterConfig
from evidenceops.mocks.thread_pool import build_thread_pool_tool
from test_knowledge_evidence import corpus


def matches():
	return tuple(replace(match,document_id="rpc-manual",source_ref="samples/knowledge/rpc_timeout.txt",
		embedding_set_id="embedding-test",config_fingerprint="test-fingerprint")
		for match in KeywordKnowledgeRetriever().search(corpus(),"线程池 重试",5))


def test_evaluation_entrypoint_search_and_context(monkeypatch):
	from evidenceops.evaluation import __main__ as evaluation
	from evidenceops.evaluation.core import EvalCase,run_suite
	from evidenceops.infrastructure import knowledge_tools
	from evidenceops.infrastructure.database import session
	from types import SimpleNamespace
	found=matches()
	tool=build_knowledge_search_tool(lambda query,**options:found[:options["top_k"]])
	engine=SimpleNamespace(dispose=lambda:None)
	monkeypatch.setattr(evaluation,"verify_fixtures",lambda case:None)
	monkeypatch.setattr(session.DatabaseSettings,"from_environment",lambda:None)
	monkeypatch.setattr(session,"create_database_engine",lambda settings:engine)
	monkeypatch.setattr(session,"create_session_factory",lambda value:None)
	monkeypatch.setattr(knowledge_tools,"configured_knowledge_tools",lambda persistence:(tool,))
	chunk=found[0].chunk.chunk_id
	case=EvalCase(case_id="knowledge-eval",description="查询线程池重试",expected_status="succeeded",expected_error_code=None,
		tool_calls=({"tool_name":"search_knowledge","arguments":{"query":"线程池 重试","top_k":3}},),
		required_sources=("knowledge",),review_criteria=("知识只是参考",),fixture_hashes={"fixture":"hash"},
		required_chunk_ids=(chunk,),retrieval_expectations={"top_k":3,"relevant_chunk_ids":[chunk]})
	report=run_suite((case,),lambda item:evaluation.case_service(item,"mock"),"mock")
	result=report["results"][0]
	assert result["execution_error"] is None
	assert result["rule_passed"],result["checks"]
	assert result["metrics"]["required_chunk_recall"]==1
	assert result["metrics"]["context_recall"]==1
	assert result["context_audits"][-1]["visible_evidence_ids"]
	assert result["knowledge_evidence"][0]["source_metadata"]["chunk_id"]==chunk


def test_evaluation_detects_wrong_version_snapshot_and_round():
	from evidenceops.application.token_budget import ContextConfig
	from evidenceops.evaluation.core import EvalCase,check_execution
	found=matches()[:3]
	def answer(request):
		items=json.loads(request.messages[-1]["content"])["data"]["matches"]
		return draft([item["evidence_id"] for item in items])
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("search","search_knowledge",{"query":"线程池 重试"}),answer)),
		"mock",(build_knowledge_search_tool(lambda query,**options:found),),"order-service",context_config=ContextConfig())
	try:
		result=assembly.diagnosis_service.execute("eval-negative","查询线程池")
		case=EvalCase(case_id="negative",description="查询线程池",expected_status="succeeded",expected_error_code=None,
			tool_calls=({"tool_name":"search_knowledge","arguments":{"query":"线程池 重试"}},),required_sources=("knowledge",),
			review_criteria=("引用正确",),fixture_hashes={"fixture":"hash"},required_chunk_ids=(found[0].chunk.chunk_id,),
			retrieval_expectations={"top_k":3,"source_versions":[result.evidences[0].source_version]})
		assert all(item["passed"] for item in check_execution(case,result))
		wrong=replace(case,retrieval_expectations={"source_versions":["wrong-version"]})
		checks={item["name"]:item["passed"] for item in check_execution(wrong,result)}
		assert not checks["retrieval_source_versions"]
		audit=replace(result.context_audits[-1],model_request_id="wrong-request")
		checks={item["name"]:item["passed"] for item in check_execution(case,replace(result,context_audits=(audit,)))}
		assert not checks["required_chunks_visible"]
		altered=replace(result.context_audits[-1].assembly,messages=())
		audit=replace(result.context_audits[-1],assembly=altered)
		checks={item["name"]:item["passed"] for item in check_execution(case,replace(result,context_audits=(audit,)))}
		assert not checks["visible_evidence_snapshots"]
	finally:
		assembly.close()


def draft(ids):
	return StructuredFinalAnswer({"root_cause":{"text":"资料不足以确认本次故障根因","evidence_ids":ids},
		"recommendations":[{"text":"依据手册补查线程池与重试记录","evidence_ids":ids}],
		"confidence":0.2,"limitations":"手册仅为参考，不是本次故障观测"})


@pytest.fixture
def persistence(tmp_path):
	engine=create_engine("sqlite:///"+str(tmp_path/"knowledge.sqlite"),connect_args={"check_same_thread":False})
	Base.metadata.create_all(engine)
	yield SqlAlchemyDiagnosisPersistence(sessionmaker(bind=engine,expire_on_commit=False),engine)
	engine.dispose()


@pytest.fixture(params=("sqlite","postgres"))
def bm25_agent_persistence(request,tmp_path):
	if request.param=="sqlite":
		engine=create_engine("sqlite:///"+str(tmp_path/"bm25-agent.sqlite"),connect_args={"check_same_thread":False})
		Base.metadata.create_all(engine)
		try:
			yield SqlAlchemyDiagnosisPersistence(sessionmaker(bind=engine,expire_on_commit=False),engine)
		finally:
			engine.dispose()
		return
	if not os.getenv("POSTGRES_PASSWORD"):
		pytest.skip("需要POSTGRES_PASSWORD")
	settings=DatabaseSettings.from_environment()
	engine=create_database_engine(settings)
	schema="bm25_agent_"+uuid4().hex
	try:
		with engine.begin() as connection:
			connection.execute(CreateSchema(schema))
		test_engine=engine.execution_options(schema_translate_map={None:schema})
		Base.metadata.create_all(test_engine)
		factory=sessionmaker(bind=test_engine,expire_on_commit=False)
		yield SqlAlchemyDiagnosisPersistence(factory,engine)
	finally:
		engine.dispose()
		cleanup_engine=create_database_engine(settings)
		try:
			with cleanup_engine.begin() as connection:
				connection.execute(DropSchema(schema,cascade=True,if_exists=True))
		finally:
			cleanup_engine.dispose()


@pytest.mark.parametrize("outcome",["success","protocol","forged","timeout"])
@pytest.mark.parametrize("hybrid",[False,True,"bm25","hybrid_bm25"])
def test_model_sees_snapshots_and_ids_before_report_and_history(persistence,outcome,hybrid):
	found=matches()
	if hybrid is True: found=fuse_rankings(found,tuple(reversed(found)),5)
	if hybrid in ("bm25","hybrid_bm25"):
		lexical=bm25_ranking(found,"线程池 重试",5)
		found=lexical if hybrid=="bm25" else fuse_rankings(found,lexical,5,keyword_name="bm25")
	assert len(found)>=2
	observed=[]
	def final(request):
		payload=json.loads(request.messages[-1]["content"])
		assert payload["evidence_id"] is None
		fragments=payload["data"]["matches"]
		assert len(fragments)==len(found)
		for fragment,match in zip(fragments,found):
			assert fragment["content"]==match.chunk.content
			assert fragment["metadata"]["chunk_id"]==match.chunk.chunk_id
			assert fragment["metadata"]["embedding_set_id"]=="embedding-test"
		observed.extend(fragments)
		if outcome=="protocol": raise ModelProviderError("MODEL_PROTOCOL_ERROR","无效响应")
		if outcome=="timeout": raise TimeoutError("模型超时")
		return draft(["forged-id"] if outcome=="forged" else [item["evidence_id"] for item in fragments])
	tool=build_knowledge_search_tool(lambda query,**options:found)
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge-1","search_knowledge",{"query":"线程池 重试"}),final)),
		"mock",(tool,),"order-service",diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute("request-test","查询排障参考资料")
		response=to_response(result)
		history=history_response(load_diagnosis_history(persistence,result.run.run_id))
		assert len(result.evidences)==len(found)
		assert len(result.execution_records)==3
		assert history["execution_records"][1]["query_arguments"]=={"query":"线程池 重试"}
		for saved,live,visible in zip(history["evidences"],response["evidences"],observed):
			assert saved["content_snapshot"]==live["content_snapshot"]==visible["content"]
			assert saved["evidence_id"]==visible["evidence_id"]
			assert saved["source_metadata"]==visible["metadata"]
		if outcome=="success":
			assert history["status"]=="succeeded" and history["report"] is not None
		else:
			assert history["status"]=="failed" and history["report"] is None
			assert history["error_code"]=={"protocol":"MODEL_PROTOCOL_ERROR","forged":"INVALID_REPORT_EVIDENCE","timeout":"MODEL_TIMEOUT"}[outcome]
	finally:
		assembly.close()


def test_empty_knowledge_result_has_no_evidence_but_other_tools_still_work(persistence):
	def final(request):
		payloads=[json.loads(message["content"]) for message in request.messages if message["role"]=="tool"]
		assert payloads[0]["data"]["matches"]==[] and payloads[0]["evidence_id"] is None
		return draft([payloads[1]["evidence_id"]])
	tools=(build_knowledge_search_tool(lambda query,**options:()),build_thread_pool_tool())
	provider=MockProvider((ToolCallBatch((ToolCall("empty","search_knowledge",{"query":"不存在的资料"}),
		ToolCall("metric","query_thread_pool_snapshot",{"service_name":"order-service"}))),final))
	assembly=build_agent_diagnosis_assembly(provider,"mock",tools,"order-service",diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute("request-empty","查询日志与参考手册")
		assert result.run.status.value=="succeeded"
		assert len(result.evidences)==1 and result.evidences[0].source.value=="metric"
	finally: assembly.close()


def test_knowledge_reference_without_incident_observations_is_insufficient(persistence):
	found=matches()
	seen=[]
	def insufficient(request):
		message=next(item for item in request.messages if item["role"]=="tool")
		payload=json.loads(message["content"])
		assert payload["data"]["matches"]
		seen.extend(payload["data"]["matches"])
		return StructuredFinalAnswer({"outcome":"insufficient_evidence",
			"reason":"排障手册只能提供核验方法，当前没有服务运行时信息确认根因。",
			"missing_information":["服务实际使用的sys.executable","同一解释器下python -m pip show pandas的结果"]})
	tool=build_knowledge_search_tool(lambda query,**options:found)
	provider=MockProvider((ToolCall("root-cause-reference","search_knowledge",{"query":"ModuleNotFoundError pandas 根因"}),insufficient))
	assembly=build_agent_diagnosis_assembly(provider,"mock",(tool,),"order-service",diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute("request-root-cause-reference","ModuleNotFoundError pandas，终端pip安装过，这次根因是什么")
		history=history_response(load_diagnosis_history(persistence,result.run.run_id))
		response=to_response(result)
		assert result.run.error_code=="EVIDENCE_INSUFFICIENT"
		assert result.report is None and history["report"] is None
		assert history["status"]=="failed" and len(history["evidences"])==len(seen)>0
		assert history["error_detail"]["missing_information"]==[
			"服务实际使用的sys.executable","同一解释器下python -m pip show pandas的结果"]
		assert [item["content_snapshot"] for item in response["evidences"]]==[item["content"] for item in seen]
	finally:
		assembly.close()


def test_bm25_agent_stream_and_history_without_embedding(bm25_agent_persistence,monkeypatch):
	from fastapi.testclient import TestClient
	from evidenceops.infrastructure import knowledge_tools
	from evidenceops.application.vector_knowledge import VectorKnowledgeService
	content=("# Python 导入故障\n\n"
		"ModuleNotFoundError 表示当前运行的 Python 解释器没有找到导入模块。\n\n"
		"使用服务实际启动的解释器执行 python -m pip show pandas，确认安装位置和运行环境一致。")
	document=KnowledgeDocument("bm25-agent-"+uuid4().hex,"Python 导入故障手册","acceptance:python-import")
	version=DocumentVersion(document.document_id,document.source_ref,content)
	chunk_set=ChunkSet(version.version_id,SplitterConfig())
	chunks=KnowledgeSplitter().split(version,chunk_set)
	with bm25_agent_persistence._session_factory.begin() as session:
		SqlAlchemyKnowledgeRepository(session).save_ingestion(document,version,chunk_set,chunks)
	VectorKnowledgeService(bm25_agent_persistence._session_factory).publish_chunk_set(document.document_id,chunk_set.chunk_set_id)
	with bm25_agent_persistence._session_factory() as session:
		publication=VectorRepository(session).active_publication(document.document_id)
	assert publication==(chunk_set.chunk_set_id,None)
	monkeypatch.setenv("EVIDENCEOPS_KNOWLEDGE_ENABLED","true")
	monkeypatch.setenv("EVIDENCEOPS_KNOWLEDGE_DOCUMENT_IDS",document.document_id)
	monkeypatch.setenv("EVIDENCEOPS_KNOWLEDGE_RETRIEVAL","bm25")
	for name in ("EMBEDDING_PROVIDER","EMBEDDING_ENDPOINT","EMBEDDING_MODEL","EMBEDDING_DIMENSIONS","EMBEDDING_API_KEY","DASHSCOPE_API_KEY"):
		monkeypatch.delenv(name,raising=False)
	monkeypatch.setattr(knowledge_tools,"configured_embedding_provider",lambda:pytest.fail("BM25不应创建Embedding Provider"))
	tools=configured_knowledge_tools(bm25_agent_persistence)
	assert len(tools)==1 and tools[0].name=="search_knowledge"
	visible=[]
	def final(request):
		tool_messages=[message for message in request.messages if message["role"]=="tool"]
		assert len(tool_messages)==1
		payload=json.loads(tool_messages[0]["content"])
		matches=payload["data"]["matches"]
		assert matches
		assert any("ModuleNotFoundError" in item["content"] for item in matches)
		assert any("pandas" in item["content"] for item in matches)
		assert all(item["metadata"]["embedding_set_id"] is None for item in matches)
		assert all(item["metadata"]["retrieval_method"]=="bm25-v1" for item in matches)
		visible.extend(matches)
		identities=[item["evidence_id"] for item in matches]
		return StructuredFinalAnswer({
			"root_cause":{"text":"目前没有运行时证据，无法确认pandas是否安装在服务实际使用的解释器中。","evidence_ids":identities},
			"recommendations":[{"text":"使用服务启动时的解释器执行python -m pip show pandas，并记录sys.executable。","evidence_ids":identities}],
			"confidence":0.2,"limitations":"检索到的是排障参考手册，不是本次服务的运行时观测。"})
	provider=MockProvider((ToolCall("bm25-agent-search","search_knowledge",{
		"query":"ModuleNotFoundError pandas Python解释器","top_k":3}),final))
	assembly=build_agent_diagnosis_assembly(provider,"mock",tools,"order-service",diagnosis_persistence=bm25_agent_persistence)
	try:
		with TestClient(create_app(assembly)) as client:
			capabilities=client.get("/api/v1/agent/capabilities").json()
			assert capabilities["knowledge_search"] is True
			response=client.post("/api/v1/agent/diagnosis/stream",json={"description":"排查ModuleNotFoundError pandas"})
			assert response.status_code==200
			events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
			assert [event["event"] for event in events]==[
				"run_started","model_started","model_finished","tool_started","tool_finished",
				"model_started","model_finished","run_completed"]
			result=events[-1]["data"]["result"]
			assert result["status"]=="succeeded" and result["report"] is not None
			history=client.get("/api/v1/agent/runs/"+result["run_id"]).json()
			assert history["status"]=="succeeded" and history["error_code"] is None
			assert len(history["evidences"])==len(visible)>0
			assert history["execution_records"][1]["query_arguments"]=={
				"query":"ModuleNotFoundError pandas Python解释器","top_k":3}
			for saved,live,model_visible in zip(history["evidences"],result["evidences"],visible):
				assert saved["content_snapshot"]==live["content_snapshot"]==model_visible["content"]
				assert saved["evidence_id"]==live["evidence_id"]==model_visible["evidence_id"]
				assert saved["source_metadata"]["embedding_set_id"] is None
				assert saved["source_metadata"]["retrieval_method"]=="bm25-v1"
				assert saved["source_metadata"]==model_visible["metadata"]
				assert saved["evidence_id"] in result["report"]["root_cause"]["evidence_ids"]
	finally:
		assembly.close()


@pytest.mark.parametrize("arguments",[{"query":" "},{"query":"x","top_k":True},{"query":"x","top_k":6},{"query":"x","path":"secret"}])
def test_invalid_arguments_do_not_retrieve(arguments):
	tool=build_knowledge_search_tool(lambda *args,**kwargs:pytest.fail("不应调用检索"))
	with ToolRuntimeContext(tool) as runtime:
		assert runtime.execute("search_knowledge",arguments).error_code=="INVALID_ARGUMENTS"


class ToolRuntimeContext:
	def __init__(self,tool): self.runtime=ToolRuntime((tool,))
	def __enter__(self): return self.runtime
	def __exit__(self,*args): self.runtime.close()


@pytest.mark.parametrize("failure",["backend","malformed","oversized"])
def test_retrieval_errors_are_not_empty_success_or_secret_leaks(failure):
	def search(*args,**kwargs):
		if failure=="backend": raise RuntimeError("secret-api-key")
		if failure=="malformed": return ["not a match"]
		return matches()*10
	with ToolRuntimeContext(build_knowledge_search_tool(search)) as runtime:
		result=runtime.execute("search_knowledge",{"query":"RPC"})
		assert not result.ok and result.error_code=="TOOL_EXECUTION_FAILED"
		assert "secret-api-key" not in result.error_message


def test_cancelled_search_discards_late_result():
	control=RunControl()
	started=Event()
	def search(*args,**kwargs):
		started.set()
		control.request_cancel()
		return matches()
	with ToolRuntimeContext(build_knowledge_search_tool(search)) as runtime:
		result=runtime.execute("search_knowledge",{"query":"RPC"},control=control)
		assert started.is_set() and result.error_code=="RUN_CANCELLED" and result.data is None


def test_snapshot_hash_cannot_mismatch():
	from evidenceops.application.knowledge_evidence import matches_to_evidence
	item=matches_to_evidence("run-test","call-test",matches())[0]
	with pytest.raises(ValueError,match="哈希"): replace(item,content_snapshot="篡改的正文")


@pytest.mark.parametrize("method",["keyword","bm25","hybrid_bm25"])
def test_sse_terminal_and_history_have_same_knowledge_snapshots(persistence,method):
	from fastapi.testclient import TestClient
	from evidenceops.api.agent_diagnosis import create_app
	found=matches()
	if method!="keyword":
		lexical=bm25_ranking(found,"RPC 线程池 重试",5)
		found=lexical if method=="bm25" else fuse_rankings(found,lexical,5,keyword_name="bm25")
	def final(request):
		fragments=json.loads(request.messages[-1]["content"])["data"]["matches"]
		return draft([item["evidence_id"] for item in fragments])
	tool=build_knowledge_search_tool(lambda query,**options:found)
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge-sse","search_knowledge",{"query":"RPC"}),final)),
		"mock",(tool,),"order-service",diagnosis_persistence=persistence)
	with TestClient(create_app(assembly)) as client:
		assert client.get("/api/v1/agent/capabilities").json()["knowledge_search"] is True
		response=client.post("/api/v1/agent/diagnosis/stream",json={"description":"查询RPC排障手册"})
		assert response.status_code==200
		payloads=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
		terminal=next(item for item in payloads if item.get("event")=="run_completed")
		result=terminal["data"]["result"]
		history=client.get("/api/v1/agent/runs/"+result["run_id"]).json()
		assert len(history["evidences"])>=2
		assert history["evidences"][0]["content_snapshot"]==result["evidences"][0]["content_snapshot"]
		# 历史证据另含run_id，只比较诊断接口实际公开的字段。
		assert [{key:saved[key] for key in live} for saved,live in zip(history["evidences"],result["evidences"])]==result["evidences"]
		if method!="keyword":
			assert history["evidences"][0]["source_metadata"]["retrieval_details"]==found[0].retrieval_details


def test_retrieval_failure_stops_diagnosis_but_keeps_parallel_observation(persistence):
	def fail(*args,**kwargs): raise ConnectionError("secret")
	tools=(build_knowledge_search_tool(fail),build_thread_pool_tool())
	provider=MockProvider((ToolCallBatch((ToolCall("knowledge","search_knowledge",{"query":"RPC"}),
		ToolCall("metric","query_thread_pool_snapshot",{"service_name":"order-service"}))),))
	assembly=build_agent_diagnosis_assembly(provider,"mock",tools,"order-service",diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute("request-failure","查询RPC相关证据")
		assert result.run.error_code=="TOOL_EXECUTION_FAILED" and result.report is None
		assert len(result.evidences)==1 and result.evidences[0].source.value=="metric"
		assert len(result.execution_records)==3
	finally: assembly.close()


def test_empty_only_result_cannot_fabricate_report(persistence):
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("empty","search_knowledge",{"query":"RPC"}),draft(["invented"]))),
		"mock",(build_knowledge_search_tool(lambda query,**options:()),),"order-service",diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute("request-only-empty","查询不存在的参考资料")
		assert result.run.error_code=="EVIDENCE_INSUFFICIENT" and result.evidences==() and result.report is None
	finally: assembly.close()


def test_migrated_database_accepts_knowledge_evidence(tmp_path):
	from evidenceops.infrastructure.local_storage import migrate
	engine=create_engine("sqlite:///"+str(tmp_path/"migrated.sqlite"))
	try:
		migrate(engine)
		store=SqlAlchemyDiagnosisPersistence(sessionmaker(bind=engine,expire_on_commit=False))
		# 同时覆盖正文保存和CHECK约束；create_all无法发现迁移遗漏。
		test_model_sees_snapshots_and_ids_before_report_and_history(store,"success",True)
	finally: engine.dispose()


def test_tool_timeout_and_total_budget_remain_distinct():
	from evidenceops.application.run_budget import RunBudget
	def timeout(*args,**kwargs): raise TimeoutError("供应商超时")
	with ToolRuntimeContext(build_knowledge_search_tool(timeout)) as runtime:
		assert runtime.execute("search_knowledge",{"query":"RPC"}).error_code=="TOOL_TIMEOUT"
		assert runtime.execute("search_knowledge",{"query":"RPC"},budget=RunBudget(0.000001)).error_code=="RUN_TIMEOUT"


def test_disabled_or_memory_configuration(monkeypatch):
	from evidenceops.infrastructure.knowledge_tools import configured_knowledge_tools
	monkeypatch.delenv("EVIDENCEOPS_KNOWLEDGE_ENABLED",raising=False)
	assert configured_knowledge_tools(None)==()
	monkeypatch.setenv("EVIDENCEOPS_KNOWLEDGE_ENABLED","true")
	with pytest.raises(ValueError,match="持久化"): configured_knowledge_tools(None)
