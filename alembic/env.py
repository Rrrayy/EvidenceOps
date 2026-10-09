from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from evidenceops.infrastructure.database.models import Base
from evidenceops.infrastructure.database.session import DatabaseSettings,build_database_url,create_database_engine


config=context.config

if config.config_file_name is not None:
	fileConfig(config.config_file_name)

target_metadata=Base.metadata


def run_migrations_offline()->None:
	settings=DatabaseSettings.from_environment()
	database_url=build_database_url(settings).render_as_string(hide_password=True)

	context.configure(
		url=database_url,
		target_metadata=target_metadata,
		literal_binds=True,
		dialect_opts={"paramstyle":"named"},
		compare_type=True,
	)

	with context.begin_transaction():
		context.run_migrations()


def run_migrations_online()->None:
	settings=DatabaseSettings.from_environment()
	engine=create_database_engine(settings)

	try:
		with engine.connect() as connection:
			context.configure(
				connection=connection,
				target_metadata=target_metadata,
				compare_type=True,
				poolclass=pool.NullPool,
			)

			with context.begin_transaction():
				context.run_migrations()
	finally:
		engine.dispose()


if context.is_offline_mode():
	run_migrations_offline()
else:
	run_migrations_online()
