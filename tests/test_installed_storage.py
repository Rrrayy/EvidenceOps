"""验证本机安装、历史持久化、维护回滚、备份凭据及跨数据库恢复。"""
import json
import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from evidenceops.api.installed_app import create_installed_app
from evidenceops.api.agent_app import build_agent_app
from evidenceops.infrastructure.local_storage import LocalPersistence

def operation(client,action,**values):
	installation=client.app.state.installation
	response=client.post("/api/v1/agent/storage/operations",json={"action":action,"expected_version":installation.config["version"],"request_id":str(uuid4()),**values},headers={"x-evidenceops-admin":installation.token})
	assert response.status_code==202,response.text
	identity=response.json()["id"]
	for attempt in range(200):
		result=client.get("/api/v1/agent/storage/operations/"+identity).json()
		if result["status"] in ("succeeded","failed"): return result
		time.sleep(0.05)
	raise AssertionError("维护任务未完成")

def test_installation_history_and_restart(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	app=create_installed_app(tmp_path,build_agent_app)
	with TestClient(app) as client:
		state=client.get("/api/v1/agent/storage/status").json()
		assert state["state"]=="ready" and state["mode"]=="sqlite"
		assert state["schema_version"]=="0005"
		response=client.post("/api/v1/agent/diagnosis",json={"description":"模拟订单 RPC 超时"}).json()
		identity=response["run_id"]
		assert response["status"]=="succeeded"
		assert client.get("/api/v1/agent/runs/"+identity).json()["model_config"]["model_id"]=="mock-model"
		assert operation(client,"complete_setup")["status"]=="succeeded"
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		assert client.get("/api/v1/agent/storage/status").json()["setup_completed"]
		assert client.get("/api/v1/agent/runs/"+identity).json()["status"]=="succeeded"
		assert client.get("/api/v1/agent/runs/"+identity+"/events").json()["events"]

def test_archive_restore_and_corruption(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		original=client.post("/api/v1/agent/diagnosis",json={"description":"原始诊断"}).json()
		backup=operation(client,"backup")
		assert backup["status"]=="succeeded"
		archive=client.get("/api/v1/agent/storage/backups/"+backup["backup_id"]).json()
		assert "credentials" not in archive["payload"]
		assert "model_config" in archive["payload"]["tables"]["diagnosis_runs"][0]
		client.post("/api/v1/agent/diagnosis",json={"description":"备份之后的诊断"})
		restored=operation(client,"restore",backup_id=backup["backup_id"],confirmation="恢复备份")
		assert restored["status"]=="succeeded",restored
		assert len(client.get("/api/v1/agent/runs").json()["items"])==1
		assert client.get("/api/v1/agent/runs/"+original["run_id"]).json()["report"]==original["report"]
		path=tmp_path/"backups"/(backup["backup_id"]+".json")
		archive["payload"]["tables"]["diagnosis_runs"][0]["description"]="篡改";path.write_text(json.dumps(archive),encoding="utf-8")
		failed=operation(client,"restore",backup_id=backup["backup_id"],confirmation="恢复备份")
		assert failed["status"]=="failed"
		assert client.get("/api/v1/agent/runs/"+original["run_id"]).json()["description"]=="原始诊断"

def test_maintenance_authorization_and_duplicate(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		body={"action":"backup","expected_version":0,"request_id":str(uuid4())}
		assert client.post("/api/v1/agent/storage/operations",json=body).status_code==403
		headers={"x-evidenceops-admin":client.app.state.installation.token}
		first=client.post("/api/v1/agent/storage/operations",json=body,headers=headers).json()
		second=client.post("/api/v1/agent/storage/operations",json=body,headers=headers).json()
		assert first["id"]==second["id"]
		assert client.post("/api/v1/agent/storage/check",json={"mode":"postgres","password":"secret","port":0},headers=headers).status_code==422
		assert "secret" not in client.post("/api/v1/agent/storage/check",json={"password":"secret","port":0},headers=headers).text
		assert client.get("/api/v1/agent/storage/status").json().get("token") is None

def test_single_instance_lock(tmp_path):
	first=LocalPersistence(tmp_path/"diagnosis.sqlite");second=LocalPersistence(tmp_path/"diagnosis.sqlite")
	try:
		first.acquire_instance_lock()
		with pytest.raises(RuntimeError): second.acquire_instance_lock()
		first.close();second.acquire_instance_lock()
	finally: first.close();second.close()

def test_failed_activation_preserves_original_storage(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		installation=client.app.state.installation;original=client.post("/api/v1/agent/diagnosis",json={"description":"不能丢失的历史"}).json()
		original_start=installation.start_child;calls=[]
		async def failed_start(persistence):
			calls.append(persistence)
			if len(calls)==1: persistence.close();raise RuntimeError("不得回显的内部凭据")
			await original_start(persistence)
		monkeypatch.setattr(installation,"start_child",failed_start) # 不修改任何客户目录。
		result=operation(client,"switch",storage={"mode":"sqlite"})
		assert result["status"]=="failed" and "内部凭据" not in result["message"]
		assert installation.config["version"]==0
		assert client.get("/api/v1/agent/runs/"+original["run_id"]).json()["report"]==original["report"]

def test_database_failure_leaves_management_available(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	app=create_installed_app(tmp_path,build_agent_app)
	def fail_prepare(*values): raise RuntimeError("数据库无法连接")
	monkeypatch.setattr(app.state.installation,"prepare",fail_prepare) # 管理仍走完整生命周期。
	with TestClient(app) as client:
		assert client.get("/api/v1/agent/storage/status").json()["state"]=="failed"
		assert client.get("/api/v1/agent/model-connections").status_code==200
		assert client.post("/api/v1/agent/diagnosis",json={"description":"不应该启动"}).status_code==503
		assert client.get("/api/v1/agent/runs").status_code==503

def test_portable_backup_and_malformed_import(tmp_path,monkeypatch):
	from evidenceops.infrastructure.storage_archive import validate_archive,restore_connections,canonical
	import hashlib
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		installation=client.app.state.installation;secret="test-key-never-in-backup"
		connection=installation.store.save({"name":"测试连接","provider_id":"qianwen","protocol":"chat_completions","endpoint":"https://dashscope.aliyuncs.com/compatible-mode/v1","default_model":"qwen-plus","timeout_seconds":30,"api_key":secret})
		password="independent-portable-password";result=operation(client,"backup",passphrase=password)
		assert result["status"]=="succeeded",result
		archive=client.get("/api/v1/agent/storage/backups/"+result["backup_id"]).json()
		assert secret not in json.dumps(archive) and password not in json.dumps(archive)
		with pytest.raises(ValueError): validate_archive(archive,"incorrect-password")
		payload,credentials=validate_archive(archive,password);assert credentials[connection["id"]]==secret
		restore_connections(installation.store,payload,{})
		assert installation.store.listing()["items"][0]["key_configured"] is False
		archive["payload"]["connections"]=[None];archive["sha256"]=hashlib.sha256(canonical(archive["payload"])).hexdigest()
		assert client.post("/api/v1/agent/storage/backups/import",json=archive,headers={"x-evidenceops-admin":installation.token}).status_code==422

def test_maintenance_waits_and_blocks_new_diagnosis(tmp_path,monkeypatch):
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		installation=client.app.state.installation;installation.store.active["system"]=1
		try:
			response=client.post("/api/v1/agent/storage/operations",json={"action":"backup","expected_version":0,"request_id":str(uuid4())},headers={"x-evidenceops-admin":installation.token})
			assert response.status_code==202
			assert client.get("/api/v1/agent/storage/operations/"+response.json()["id"]).json()["status"]=="waiting"
			assert client.post("/api/v1/agent/diagnosis",json={"description":"维护中不得开始"}).status_code==503
			assert client.get("/api/v1/agent/model-connections").status_code==200
		finally: installation.store.active.clear()
		for attempt in range(100):
			result=client.get("/api/v1/agent/storage/operations/"+response.json()["id"]).json()
			if result["status"]=="succeeded": break
			time.sleep(0.05)
		assert result["status"]=="succeeded"

def test_interrupted_restore_rolls_back_connections(tmp_path,monkeypatch):
	import sqlite3
	from evidenceops.infrastructure.storage_archive import atomic_json
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		installation=client.app.state.installation;backup=tmp_path/"connections-before-test.sqlite"
		with sqlite3.connect(installation.store.path) as source,sqlite3.connect(backup) as target: source.backup(target)
		installation.store.save({"name":"未提交的恢复配置","provider_id":"qianwen","protocol":"chat_completions","endpoint":"https://dashscope.aliyuncs.com/compatible-mode/v1","default_model":"qwen-plus","timeout_seconds":30,"api_key":"test-only-key"})
		atomic_json(tmp_path/"maintenance.json",{"old_version":0,"connections_backup":backup.name})
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		assert client.get("/api/v1/agent/model-connections").json()["items"]==[]
		assert client.get("/api/v1/agent/storage/status").json()["state"]=="ready"
		assert not (tmp_path/"maintenance.json").exists()

@pytest.mark.skipif(__import__("os").getenv("EVIDENCEOPS_TEST_POSTGRES")!="1",reason="显式启用才访问隔离 PostgreSQL schema")
def test_sqlite_archive_import_to_postgres(tmp_path,monkeypatch):
	from sqlalchemy import event,text,select
	from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine
	from evidenceops.infrastructure.database.models import Base,RunRow
	from evidenceops.infrastructure.storage_archive import export_archive,import_tables
	monkeypatch.delenv("EVIDENCEOPS_PERSISTENCE",raising=False)
	with TestClient(create_installed_app(tmp_path,build_agent_app)) as client:
		result=client.post("/api/v1/agent/diagnosis",json={"description":"跨数据库迁移"}).json()
		installation=client.app.state.installation;archive=export_archive(installation.child.state.assembly.diagnosis_persistence._engine,installation.store)
	settings=DatabaseSettings.from_environment();administrator=create_database_engine(settings);target=create_database_engine(settings);schema="evidenceops_archive_test_"+uuid4().hex # 不操作 public 客户表。
	try:
		with administrator.begin() as connection: connection.execute(text('CREATE SCHEMA "'+schema+'"'))
		@event.listens_for(target,"connect")
		def set_schema(connection,record):
			with connection.cursor() as cursor: cursor.execute('SET search_path TO "'+schema+'"')
			connection.commit()
		Base.metadata.create_all(target);import_tables(target,archive["payload"])
		with target.begin() as connection:
			assert connection.scalar(select(RunRow.model_config).where(RunRow.run_id==result["run_id"]))["model_id"]=="mock-model"
			maximum=connection.scalar(text("SELECT MAX(record_id) FROM execution_records"));next_value=connection.scalar(text("SELECT nextval(pg_get_serial_sequence('execution_records','record_id'))"))
			assert next_value>maximum
	finally:
		target.dispose()
		with administrator.begin() as connection: connection.execute(text('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE')) # 仅删除本次 uuid schema。
		administrator.dispose()
