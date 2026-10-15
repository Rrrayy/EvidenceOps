"""安装入口的版本升级、知识档案恢复、能力声明和失效路径。"""
import hashlib
import json
import os
from datetime import datetime,timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event,text,select

from evidenceops.api.agent_diagnosis import create_app
from evidenceops.api.installed_app import Installation,StorageFailure,create_installed_app
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ToolCall,StructuredFinalAnswer
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.connectors.knowledge_search import build_knowledge_search_tool
from evidenceops.domain.knowledge_vectors import EncodingConfig
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.models import RunRow,KnowledgePublicationRow,KnowledgeVectorRow
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.local_storage import LocalPersistence,sqlite_engine,migrate
from evidenceops.infrastructure.model_connections import ConnectionStore
from evidenceops.infrastructure.schema_versions import current_schema,database_schema,UnsupportedSchema
from evidenceops.infrastructure.storage_archive import export_archive,validate_archive,import_tables,canonical
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from test_installed_storage import operation
from test_vector_knowledge import setup_document,TestEncoder


def seed_run(engine):
	identity="archive-run-"+str(uuid4())
	with engine.begin() as connection:
		connection.execute(RunRow.__table__.insert().values(run_id=identity,request_id=identity,
			description="升级之前的历史",status="succeeded",created_at=datetime.now(timezone.utc)))
	return identity


def signed(payload):
	return {"payload":payload,"sha256":hashlib.sha256(canonical(payload)).hexdigest()}


@pytest.mark.parametrize("revision",["0001","0002","0003","0004","0005","0006","0007","0008","0009"])
def test_old_archive_normalizes_and_restores_without_inventing_snapshots(tmp_path,revision):
	engine=sqlite_engine(tmp_path/(revision+".sqlite"))
	target=LocalPersistence(tmp_path/"target.sqlite")
	store=ConnectionStore(tmp_path/"models")
	try:
		migrate(engine,revision)
		identity=seed_run(engine)
		archive=export_archive(engine,store)
		assert archive["payload"]["schema"]==revision
		original=canonical(archive)
		payload,_=validate_archive(archive)
		assert canonical(archive)==original
		assert payload["schema"]==current_schema()
		assert payload["tables"]["knowledge_publications"]==[]
		target.acquire_instance_lock()
		import_tables(target._engine,payload)
		with target._engine.connect() as connection:
			assert connection.scalar(select(RunRow.description).where(RunRow.run_id==identity))=="升级之前的历史"
			assert connection.scalar(select(RunRow.model_config).where(RunRow.run_id==identity)) is None
	finally:
		target.close();engine.dispose()


def test_sqlite_upgrade_backup_once_and_unknown_version_refused(tmp_path):
	path=tmp_path/"diagnosis.sqlite"
	engine=sqlite_engine(path)
	migrate(engine,"0005")
	identity=seed_run(engine)
	engine.dispose()
	for attempt in range(2):
		persistence=LocalPersistence(path)
		try:
			persistence.acquire_instance_lock()
			with persistence._engine.connect() as connection:
				assert database_schema(connection)==current_schema()
				assert connection.scalar(select(RunRow.run_id))==identity
		finally: persistence.close()
	assert len(list(tmp_path.glob("pre-upgrade-*.sqlite")))==1
	engine=sqlite_engine(path)
	with engine.begin() as connection: connection.execute(text("UPDATE alembic_version SET version_num='9999'"))
	engine.dispose()
	persistence=LocalPersistence(path)
	try:
		with pytest.raises(UnsupportedSchema): persistence.acquire_instance_lock()
	finally: persistence.close()
	assert len(list(tmp_path.glob("pre-upgrade-*.sqlite")))==1


def test_archive_rejects_missing_tables_fields_and_unknown_version(tmp_path):
	persistence=LocalPersistence(tmp_path/"diagnosis.sqlite")
	try:
		persistence.acquire_instance_lock()
		seed_run(persistence._engine)
		archive=export_archive(persistence._engine,ConnectionStore(tmp_path/"models"))
		payload=json.loads(json.dumps(archive["payload"]))
		payload["schema"]="0005"
		assert validate_archive(signed(payload))[0]["tables"]==archive["payload"]["tables"]
		for change in ("table","field","version"):
			broken=json.loads(json.dumps(archive["payload"]))
			if change=="table": del broken["tables"]["knowledge_publications"]
			elif change=="field": del broken["tables"]["diagnosis_runs"][0]["description"]
			else: broken["schema"]="9999"
			with pytest.raises(ValueError): validate_archive(signed(broken))
	finally: persistence.close()


def knowledge_factory(diagnosis_persistence,connection_store=None):
	encoder=TestEncoder(EncodingConfig("test","test:local","test-v1",2))
	service=VectorKnowledgeService(diagnosis_persistence._session_factory) if diagnosis_persistence else None
	def search(query,top_k,budget):
		with diagnosis_persistence._session_factory() as session:
			identity=session.scalar(select(KnowledgePublicationRow.document_id))
		return service.search(identity,query,encoder,top_k=top_k,budget=budget)
	def answer(request):
		matches=json.loads(request.messages[-1]["content"])["data"]["matches"]
		return StructuredFinalAnswer({"root_cause":{"text":"演示：知识不能确认本次根因","evidence_ids":[item["evidence_id"] for item in matches]},
			"recommendations":[{"text":"演示：补查现场观测","evidence_ids":[matches[0]["evidence_id"]]}],"confidence":0.1,"limitations":"确定性替身验收"})
	tools=(build_knowledge_search_tool(search),) if service else ()
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge","search_knowledge",{"query":"RPC","top_k":2}),answer)),
		"mock",tools,"order-service",diagnosis_persistence=diagnosis_persistence)
	# 保留安装管理所需的连接Manager，不替换或触碰用户模型配置。
	from evidenceops.api.model_connections import ConnectionManager
	return create_app(assembly,ConnectionManager(assembly,connection_store))


def test_installed_knowledge_sse_backup_restore_and_search(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,knowledge_factory)) as client:
		installation=client.app.state.installation
		persistence=installation.child.state.assembly.diagnosis_persistence
		document,chunk_set,chunks=setup_document(persistence._session_factory)
		config=EncodingConfig("test","test:local","test-v1",2)
		service=VectorKnowledgeService(persistence._session_factory)
		set_id=service.build(document.document_id,chunk_set.chunk_set_id,config,TestEncoder(config))
		service.publish(document.document_id,set_id,None)
		capabilities=client.get("/api/v1/agent/capabilities").json()
		assert capabilities["persistence"] and capabilities["knowledge_search"] and "knowledge" in capabilities["sources"]
		response=client.post("/api/v1/agent/diagnosis/stream",json={"description":"演示：知识引用与安装版恢复验收"})
		events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
		result=events[-1]["data"]["result"]
		assert result["status"]=="succeeded" and len(result["evidences"])==2
		before=client.get("/api/v1/agent/runs/"+result["run_id"]).json()
		assert [item["content_snapshot"] for item in before["evidences"]]==[item["content_snapshot"] for item in result["evidences"]]
		backup=operation(client,"backup")
		assert backup["status"]=="succeeded",backup
		restored=operation(client,"restore",backup_id=backup["backup_id"],confirmation="恢复备份")
		assert restored["status"]=="succeeded",restored
		history=client.get("/api/v1/agent/runs/"+result["run_id"]).json()
		assert history==before
		persistence=installation.child.state.assembly.diagnosis_persistence
		matches=VectorKnowledgeService(persistence._session_factory).search(document.document_id,"RPC",TestEncoder(config))
		assert matches and matches[0].embedding_set_id==set_id
		with persistence._engine.connect() as connection:
			assert connection.scalar(select(KnowledgeVectorRow.chunk_id))
		installation.maintenance=True
		try:
			capabilities=client.get("/api/v1/agent/capabilities").json()
			assert not capabilities["knowledge_search"] and "knowledge" not in capabilities["sources"]
		finally: installation.maintenance=False


@pytest.mark.skipif(os.getenv("EVIDENCEOPS_TEST_POSTGRES")!="1",reason="显式启用才访问隔离PostgreSQL schema")
def test_installed_postgres_upgrade_current_and_unknown_revision(tmp_path,monkeypatch):
	settings=DatabaseSettings.from_environment()
	admin=create_database_engine(settings)
	schema="installed_knowledge_"+uuid4().hex
	engines=[]
	installation=Installation(tmp_path)
	installation.store=ConnectionStore(tmp_path/"models")
	def engine_for_test(value):
		engine=create_database_engine(settings)
		@event.listens_for(engine,"connect")
		def set_schema(connection,record):
			with connection.cursor() as cursor: cursor.execute('SET search_path TO "'+schema+'"')
			connection.commit()
		engines.append(engine)
		store=SqlAlchemyDiagnosisPersistence(create_session_factory(engine),engine)
		store._lock_key=(1163284304,int(uuid4().hex[:7],16))
		return store
	monkeypatch.setattr(installation,"engine",engine_for_test)
	try:
		with admin.begin() as connection: connection.execute(text('CREATE SCHEMA "'+schema+'"'))
		initial=engine_for_test({})
		migrate(initial._engine,"0005")
		identity=seed_run(initial._engine)
		initial.close()
		with pytest.raises(StorageFailure) as caught: installation.prepare({"mode":"postgres"})
		assert caught.value.state=="needs_upgrade"
		prepared=installation.prepare({"mode":"postgres"},True)
		try:
			with prepared._engine.connect() as connection:
				assert database_schema(connection)==current_schema()
				assert connection.scalar(select(RunRow.run_id))==identity
		finally: prepared.close()
		assert len(installation.backups)==1
		prepared=installation.prepare({"mode":"postgres"})
		try:
			with prepared._engine.begin() as connection: connection.execute(text("UPDATE alembic_version SET version_num='9999'"))
		finally: prepared.close()
		with pytest.raises(StorageFailure) as caught: installation.prepare({"mode":"postgres"},True)
		assert caught.value.state=="unsupported_version" and len(installation.backups)==1
	finally:
		for engine in engines: engine.dispose()
		with admin.begin() as connection: connection.execute(text('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE'))
		admin.dispose()
