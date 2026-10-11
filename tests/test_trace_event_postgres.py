import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine
from evidenceops.application.event_history import load_event_page
from test_trace_event_persistence import make_assembly,read_events


@pytest.mark.skipif(os.getenv("EVIDENCEOPS_TEST_POSTGRES")!="1",reason="显式启用才访问本地PostgreSQL")
def test_postgres_migrations_and_jsonb_terminal_transaction():
	engine=create_database_engine(DatabaseSettings.from_environment())
	try:
		with engine.connect() as connection:
			outer=connection.begin()
			try:
				# 随机schema和外层事务隔离实验；最终回滚，不迁移用户public表。
				schema=f"evidenceops_event_test_{uuid4().hex}"
				connection.execute(text(f'CREATE SCHEMA "{schema}"'))
				connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
				context=MigrationContext.configure(connection)
				with Operations.context(context):
					for path in sorted((Path(__file__).parents[1]/"alembic"/"versions").glob("*.py")):
						spec=importlib.util.spec_from_file_location(path.stem,path)
						module=importlib.util.module_from_spec(spec)
						spec.loader.exec_module(module)
						module.upgrade()
				persistence=SqlAlchemyDiagnosisPersistence(sessionmaker(bind=connection,join_transaction_mode="create_savepoint"))
				assembly=make_assembly(persistence)
				try:
					result=assembly.diagnosis_service.execute("req-pg-events","PostgreSQL迁移与归档实验")
					stored=read_events(persistence,result.run.run_id)
					assert len(stored)==8 and stored[-1]["event"]=="run_completed"
					assert stored[-1]["data"]["result"]["status"]=="succeeded"
					page=load_event_page(persistence,result.run.run_id,5,2)
					assert [item["sequence"] for item in page.events]==[6,7] and page.has_more
					assert load_event_page(persistence,result.run.run_id,8).events==()
					assert connection.execute(text("SELECT pg_typeof(payload)::text FROM trace_events LIMIT 1")).scalar_one()=="jsonb"
					assert connection.execute(text("SELECT COUNT(*) FROM diagnosis_reports")).scalar_one()==1
				finally:
					assembly.close()
			finally:
				outer.rollback()
	finally:
		engine.dispose()
