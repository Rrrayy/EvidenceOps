import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine,event,func,select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect

from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.agent_loop import AgentLoopResult
from evidenceops.application.context_assembler import ContextAssembler,EvidenceProjection
from evidenceops.application.knowledge_retrieval import KeywordKnowledgeRetriever
from evidenceops.application.model_protocol import ModelProviderError,StructuredFinalAnswer,ToolCall
from evidenceops.application.run_budget import RunBudgetExceeded
from evidenceops.application.run_repository import RunPersistenceError
from evidenceops.application.token_budget import ContextConfig,HeuristicTokenEstimator,TokenLedger
from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.connectors.knowledge_search import build_knowledge_search_tool
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.infrastructure.database.context_audit_repository import ContextAuditRepository
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.models import ModelContextAuditRow
from evidenceops.infrastructure.database.run_repository import SqlAlchemyRunRepository
from evidenceops.infrastructure.local_storage import migrate
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from test_knowledge_evidence import corpus


@pytest.fixture
def audit_store(tmp_path):
	engine=create_engine("sqlite:///"+str(tmp_path/"audits.sqlite"))
	@event.listens_for(engine,"connect")
	def enable_foreign_keys(connection,record):
		connection.execute("PRAGMA foreign_keys=ON")
	# 使用现有迁移创建真实表，避免仅靠create_all掩盖迁移缺口。
	migrate(engine)
	factory=sessionmaker(bind=engine,expire_on_commit=False)
	store=SqlAlchemyDiagnosisPersistence(factory)
	try:
		yield factory,store
	finally:
		engine.dispose()


def audit_assembly():
	config=ContextConfig()
	return ContextAssembler(config).assemble(({"role":"user","content":"诊断"},),(),TokenLedger(config),(
		EvidenceProjection("first","核对解释器",identity="same"),
		EvidenceProjection("second","核对解释器",identity="same")))


def create_run(factory,run_id="run-audit"):
	with factory.begin() as session:
		SqlAlchemyRunRepository(session).create(DiagnosisRun(run_id,"request-audit","审计验证"))


def test_context_audit_fields_round_trip(audit_store):
	factory,store=audit_store
	create_run(factory)
	assembly=audit_assembly()
	with store.transaction() as transaction:
		transaction.context_audit.record("run-audit",2,"request-model",assembly)
	with factory() as session:
		row=session.scalar(select(ModelContextAuditRow))
		assert row.run_id=="run-audit" and row.model_round==2 and row.model_request_id=="request-model"
		assert row.payload_hash==assembly.reservation.payload_hash
		assert row.estimator_id==HeuristicTokenEstimator.estimator_id
		assert row.estimated_input_tokens==assembly.estimated_input_tokens
		assert row.reserved_output_tokens==assembly.reservation.max_output_tokens
		assert row.visible_evidence_ids==["first"]
		assert row.deduplication_map=={"second":"first"}
		assert row.omissions==[{"evidence_id":"second","reason":"duplicate","canonical_id":"first"}]


def test_context_audit_duplicate_is_idempotent(audit_store):
	factory,store=audit_store
	create_run(factory)
	assembly=audit_assembly()
	for repeat in range(2):
		with store.transaction() as transaction:
			transaction.context_audit.record("run-audit",1,"same-request",assembly)
			transaction.context_audit.record("run-audit",2,"same-request",assembly)
	with factory() as session:
		rows=session.scalars(select(ModelContextAuditRow)).all()
		assert len(rows)==1 and rows[0].model_round==1


def test_concurrent_duplicate_audits_do_not_abort_transactions(audit_store):
	factory,store=audit_store
	create_run(factory)
	assembly=audit_assembly()
	barrier=Barrier(4)
	def write():
		barrier.wait(timeout=5)
		with store.transaction() as transaction:
			transaction.context_audit.record("run-audit",1,"concurrent-request",assembly)
	with ThreadPoolExecutor(max_workers=4) as executor:
		futures=[executor.submit(write) for repeat in range(4)]
		for future in futures: future.result(timeout=10)
	with factory() as session:
		assert session.scalar(select(func.count()).select_from(ModelContextAuditRow))==1


def test_audit_repository_does_not_commit_callers_transaction(audit_store):
	factory,store=audit_store
	create_run(factory)
	with pytest.raises(RuntimeError,match="回滚"):
		with store.transaction() as transaction:
			transaction.context_audit.record("run-audit",1,"rollback-request",audit_assembly())
			raise RuntimeError("回滚")
	with factory() as session:
		assert session.scalar(select(func.count()).select_from(ModelContextAuditRow))==0


def test_actual_estimator_identity_is_persisted(audit_store):
	factory,store=audit_store
	create_run(factory)
	class CustomEstimator(HeuristicTokenEstimator):
		estimator_id="test-estimator-v2"
	config=ContextConfig()
	assembly=ContextAssembler(config,CustomEstimator()).assemble(({"role":"user","content":"诊断"},),(),TokenLedger(config))
	with store.transaction() as transaction:
		transaction.context_audit.record("run-audit",1,"custom-request",assembly)
	with factory() as session:
		assert session.scalar(select(ModelContextAuditRow.estimator_id))=="test-estimator-v2"


@pytest.mark.parametrize("outcome,expected_error",[("success",None),("protocol","MODEL_PROTOCOL_ERROR"),
	("timeout","MODEL_TIMEOUT"),("budget","RUN_TIMEOUT"),("cancelled",None),
	("conversion","EVIDENCE_COLLECTION_FAILED"),("unexpected","EVIDENCE_COLLECTION_FAILED"),
	("forged","INVALID_REPORT_EVIDENCE"),("insufficient","EVIDENCE_INSUFFICIENT")])
def test_diagnosis_persists_each_round_on_success_and_failure(audit_store,monkeypatch,outcome,expected_error):
	factory,store=audit_store
	found=KeywordKnowledgeRetriever().search(corpus(),"线程池 重试",5)
	tool=build_knowledge_search_tool(lambda query,**options:found)
	def final(request):
		if outcome=="protocol": raise ModelProviderError("MODEL_PROTOCOL_ERROR","模拟协议错误")
		if outcome=="timeout": raise TimeoutError("模拟模型超时")
		if outcome=="budget": raise RunBudgetExceeded("模拟预算耗尽")
		if outcome=="cancelled": request.control.request_cancel()
		if outcome=="insufficient":
			return StructuredFinalAnswer({"outcome":"insufficient_evidence","reason":"只有参考资料","missing_information":["运行时日志"]})
		fragments=json.loads(request.messages[-1]["content"])["data"]["matches"]
		ids=["forged"] if outcome=="forged" else [fragment["evidence_id"] for fragment in fragments]
		return StructuredFinalAnswer({"root_cause":{"text":"需核对运行时证据","evidence_ids":ids},
			"recommendations":[{"text":"补查日志","evidence_ids":ids}],"confidence":0.2,"limitations":"知识仅供参考"})
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge","search_knowledge",{"query":"线程池 重试"}),final)),
		"mock",(tool,),"order-service",diagnosis_persistence=store,context_config=ContextConfig())
	if outcome in ("conversion","unexpected"):
		def broken(*args):
			if outcome=="conversion": raise ToolCollectionError("INVALID_TOOL_RESULT","模拟转换失败")
			raise ValueError("模拟意外转换异常")
		monkeypatch.setattr(assembly.evidence_collector,"_convert_result",broken)
	try:
		result=assembly.diagnosis_service.execute("request-integration","查询排障参考")
		assert result.run.error_code==expected_error
		assert result.run.status.value==("succeeded" if outcome=="success" else "cancelled" if outcome=="cancelled" else "failed")
		assert (result.report is not None)==(outcome=="success")
		with factory() as session:
			rows=session.scalars(select(ModelContextAuditRow).where(ModelContextAuditRow.run_id==result.run.run_id).order_by(ModelContextAuditRow.model_round)).all()
			assert len(rows)==2
			models=[record for record in result.execution_records if record.kind=="model"]
			assert [row.model_request_id for row in rows]==[record.model_request_id for record in models]
			assert [row.payload_hash for row in rows]==[record.payload_hash for record in models]
			assert rows[0].visible_evidence_ids==[]
			assert rows[1].visible_evidence_ids==[item.evidence_id for item in result.evidences]
			assert len(result.evidences)==len(found)>0
	finally:
		assembly.close()


@pytest.mark.parametrize("failed_run",[False,True])
def test_audit_failure_rolls_back_terminal_archive(audit_store,monkeypatch,failed_run):
	factory,store=audit_store
	found=KeywordKnowledgeRetriever().search(corpus(),"线程池 重试",5)
	tool=build_knowledge_search_tool(lambda query,**options:found)
	def final(request):
		if failed_run: raise ModelProviderError("MODEL_PROTOCOL_ERROR","模拟模型失败")
		ids=[item["evidence_id"] for item in json.loads(request.messages[-1]["content"])["data"]["matches"]]
		return StructuredFinalAnswer({"root_cause":{"text":"待验证","evidence_ids":ids},
			"recommendations":[{"text":"补查日志","evidence_ids":ids}],"confidence":0.2,"limitations":"仅有手册"})
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge","search_knowledge",{"query":"线程池 重试"}),final)),"mock",(tool,),"order-service",
		diagnosis_persistence=store,context_config=ContextConfig())
	def broken(*args): raise RuntimeError("模拟审计存储失败")
	monkeypatch.setattr(ContextAuditRepository,"record",broken)
	events=[]
	try:
		with pytest.raises(RunPersistenceError):
			assembly.diagnosis_service.execute("request-rollback","审计失败不应提交终态",events.append)
		run_id=events[0]["run_id"]
		with store.transaction() as transaction:
			assert transaction.run.get(run_id).status.value=="running"
			assert transaction.execution_record.list_by_run(run_id)==()
			assert transaction.evidence.list_by_run(run_id)==()
			assert transaction.report.get(run_id) is None
		with factory() as session:
			assert session.scalar(select(func.count()).select_from(ModelContextAuditRow))==0
		assert events[-1]["event"]=="stream_failed"
		assert not any(item["event"] in ("run_failed","run_completed") for item in events)
	finally:
		assembly.close()


def test_legacy_loop_result_keeps_empty_audits():
	assert AgentLoopResult(None,(),"MODEL_TIMEOUT").context_audits==()


def test_same_request_id_in_different_runs_has_separate_audits(audit_store):
	factory,store=audit_store
	create_run(factory,"run-first")
	create_run(factory,"run-second")
	with store.transaction() as transaction:
		for run_id in ("run-first","run-second"):
			transaction.context_audit.record(run_id,1,"same-request",audit_assembly())
	with factory() as session:
		assert session.scalar(select(func.count()).select_from(ModelContextAuditRow))==2


def test_postgres_insert_compiles_with_conflict_target():
	session=Mock()
	session.get_bind.return_value.dialect.name="postgresql"
	ContextAuditRepository(session).record("run-audit",1,"request-model",audit_assembly())
	statement=session.execute.call_args.args[0]
	sql=str(statement.compile(dialect=postgres_dialect()))
	assert "ON CONFLICT (run_id, model_request_id) DO NOTHING" in sql
	assert "JSONB" in sql
	assert not session.commit.called


@pytest.mark.parametrize("context_config,expected_count,expected_error",[
	(None,0,"EVIDENCE_INSUFFICIENT"),(ContextConfig(),1,"EVIDENCE_INSUFFICIENT"),
	(ContextConfig(max_run_tokens=1),0,"RUN_TOKEN_BUDGET_EXCEEDED")])
def test_no_phantom_audit_without_an_assembled_request(audit_store,context_config,expected_count,expected_error):
	factory,store=audit_store
	provider=MockProvider((StructuredFinalAnswer({"outcome":"insufficient_evidence","reason":"缺少观测","missing_information":["日志"]}),))
	assembly=build_agent_diagnosis_assembly(provider,"mock",(),"order-service",diagnosis_persistence=store,context_config=context_config)
	try:
		result=assembly.diagnosis_service.execute("request-no-context","无资料诊断")
		assert result.run.error_code==expected_error
		with factory() as session:
			assert session.scalar(select(func.count()).select_from(ModelContextAuditRow))==expected_count
		assert len(result.context_audits)==expected_count
	finally:
		assembly.close()
