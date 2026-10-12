import os
import subprocess
import sys
from queue import Queue
from threading import Thread
from time import monotonic,sleep
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from evidenceops.application.run_recovery import recover_interrupted_runs
from evidenceops.api.agent_diagnosis import create_app
from fastapi.testclient import TestClient
from evidenceops.domain.diagnosis_run import RunStatus
from evidenceops.infrastructure.database import diagnosis_persistence as database
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine
from evidenceops.infrastructure.database.models import Base
from test_run_recovery import seed_run
from test_trace_event_persistence import read_events,make_assembly


pytestmark=pytest.mark.skipif(os.getenv("EVIDENCEOPS_TEST_POSTGRES")!="1",reason="显式启用才访问本地PostgreSQL")


def make_store():
	engine=create_database_engine(DatabaseSettings.from_environment())
	return database.SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)


@pytest.fixture
def isolated_lock(monkeypatch):
	key=(1163284305,int(uuid4().hex[:7],16))
	monkeypatch.setattr(database,"INSTANCE_LOCK_KEY",key)
	return key


def test_two_instances_and_normal_close_release(isolated_lock):
	first,second=make_store(),make_store()
	try:
		first.acquire_instance_lock()
		first.acquire_instance_lock()
		with pytest.raises(RuntimeError,match="另一个EvidenceOps"):
			second.acquire_instance_lock()
		assert second._engine.pool.checkedout()==0
		first.close()
		second.acquire_instance_lock()
		assert second._engine.pool.checkedout()==1
	finally:
		first.close()
		second.close()


def test_crashed_process_releases_session_lock(isolated_lock):
	# 子进程只获取随机测试锁，不扫描或修改用户Run；kill不调用Python清理。
	code='''import sys,time
from sqlalchemy.orm import sessionmaker
from evidenceops.infrastructure.database import diagnosis_persistence as database
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine
database.INSTANCE_LOCK_KEY=(int(sys.argv[1]),int(sys.argv[2]))
engine=create_database_engine(DatabaseSettings.from_environment())
store=database.SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)
store.acquire_instance_lock()
print("LOCK_READY",flush=True)
time.sleep(30)
'''
	process=subprocess.Popen([sys.executable,"-X","utf8","-c",code,*map(str,isolated_lock)],
		stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
	store=make_store()
	try:
		# Windows communicate在超时前未必交付管道缓存，独立读行并限定等待。
		ready=Queue()
		Thread(target=lambda:ready.put(process.stdout.readline()),daemon=True).start()
		assert ready.get(timeout=10).strip()=="LOCK_READY"
		with pytest.raises(RuntimeError,match="另一个EvidenceOps"):
			store.acquire_instance_lock()
		process.kill()
		process.communicate(timeout=5)
		deadline=monotonic()+5
		while True:
			try:
				store.acquire_instance_lock()
				break
			except RuntimeError:
				if monotonic()>=deadline:
					raise
				sleep(0.05)
	finally:
		if process.poll() is None:
			process.kill()
		process.communicate(timeout=5)
		store.close()


def test_lost_lock_connection_rejects_database_work(isolated_lock):
	store=make_store()
	try:
		store.acquire_instance_lock()
		store._instance_connection.invalidate()
		with pytest.raises(RuntimeError):
			with store.transaction():
				pytest.fail("失去锁后不能接着访问业务数据库")
		with pytest.raises(RuntimeError,match="必须重启"):
			with store.transaction():
				pass
	finally:
		store.close()


def test_real_postgres_recovery_transaction(isolated_lock):
	engine=create_database_engine(DatabaseSettings.from_environment())
	try:
		with engine.connect() as connection:
			outer=connection.begin()
			try:
				schema=f"evidenceops_recovery_test_{uuid4().hex}"
				connection.execute(text(f'CREATE SCHEMA "{schema}"'))
				connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
				Base.metadata.create_all(connection)
				store=database.SqlAlchemyDiagnosisPersistence(sessionmaker(bind=connection,join_transaction_mode="create_savepoint"))
				seed_run(store,"pg-pending",RunStatus.PENDING)
				seed_run(store,"pg-running")
				assert recover_interrupted_runs(store)==2
				assert recover_interrupted_runs(store)==0
				for identity in ("pg-pending","pg-running"):
					assert read_events(store,identity)[0]["data"]["result"]["error_code"]=="RUN_INTERRUPTED"
			finally:
				outer.rollback()
	finally:
		engine.dispose()


def test_second_app_startup_cannot_recover_first_apps_active_run(isolated_lock):
	first,second=make_store(),make_store()
	schema=f"evidenceops_instance_test_{uuid4().hex}"
	cleanup=create_database_engine(DatabaseSettings.from_environment())
	try:
		with cleanup.begin() as connection:
			connection.execute(text(f'CREATE SCHEMA "{schema}"'))
		for store in (first,second):
			store._engine=store._engine.execution_options(schema_translate_map={None:schema})
			store._session_factory=sessionmaker(store._engine)
		Base.metadata.create_all(first._engine)
		with TestClient(create_app(make_assembly(first))):
			seed_run(first,"still-active")
			with pytest.raises(RuntimeError,match="另一个EvidenceOps"):
				with TestClient(create_app(make_assembly(second))):
					pytest.fail("第二实例不能开放请求")
			with first.transaction() as transaction:
				assert transaction.run.get("still-active").status==RunStatus.RUNNING
			assert read_events(first,"still-active")==()
	finally:
		first.close()
		second.close()
		# 删除对象只限本测试明确创建的随机schema，不接触public。
		with cleanup.begin() as connection:
			connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
		cleanup.dispose()
