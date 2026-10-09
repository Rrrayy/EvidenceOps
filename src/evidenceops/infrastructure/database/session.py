from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os

from sqlalchemy import Engine,create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session,sessionmaker


@dataclass(frozen=True,slots=True)
class DatabaseSettings:
	host:str
	port:int
	database:str
	user:str
	password:str
	pool_size:int=5
	max_overflow:int=5
	pool_timeout:float=5.0
	connect_timeout:int=5

	def __post_init__(self)->None:
		if not self.host.strip():
			raise ValueError("数据库主机不能为空")
		if not 1<=self.port<=65535:
			raise ValueError("数据库端口无效")
		if not self.database.strip():
			raise ValueError("数据库名不能为空")
		if not self.user.strip():
			raise ValueError("数据库用户不能为空")
		if not self.password:
			raise ValueError("数据库密码不能为空")
		if self.pool_size<1:
			raise ValueError("连接池大小必须大于0")
		if self.max_overflow<0:
			raise ValueError("连接池溢出数量不能小于0")
		if self.pool_timeout<=0:
			raise ValueError("连接池等待时间必须大于0")
		if self.connect_timeout<=0:
			raise ValueError("数据库连接超时时间必须大于0")

	@classmethod
	def from_environment(cls)->DatabaseSettings:
		password=os.getenv("POSTGRES_PASSWORD")
		if password is None:
			raise RuntimeError("缺少POSTGRES_PASSWORD环境变量")

		try:
			port=int(os.getenv("POSTGRES_PORT","5433"))
		except ValueError as error:
			raise RuntimeError("POSTGRES_PORT必须是整数") from error

		return cls(
			host=os.getenv("POSTGRES_HOST","127.0.0.1"),
			port=port,
			database=os.getenv("POSTGRES_DB","evidenceops"),
			user=os.getenv("POSTGRES_USER","evidenceops"),
			password=password,
		)


def build_database_url(settings:DatabaseSettings)->URL:
	# URL 对象处理密码中的特殊字符，避免手工拼接破坏连接地址。
	return URL.create(
		drivername="postgresql+psycopg",
		username=settings.user,
		password=settings.password,
		host=settings.host,
		port=settings.port,
		database=settings.database,
	)


def create_database_engine(settings:DatabaseSettings)->Engine:
	# 借出前检测连接存活，减少容器重启后的失效连接；不自动重试事务。
	return create_engine(
		build_database_url(settings),
		pool_pre_ping=True,
		pool_size=settings.pool_size,
		max_overflow=settings.max_overflow,
		pool_timeout=settings.pool_timeout,
		connect_args={"connect_timeout":settings.connect_timeout},
	)


def create_session_factory(engine:Engine)->sessionmaker[Session]:
	return sessionmaker(bind=engine,class_=Session,autoflush=False,expire_on_commit=False)


@contextmanager
def session_scope(session_factory:sessionmaker[Session])->Iterator[Session]:
	with session_factory() as session:
		yield session


@contextmanager
def transaction_scope(session_factory:sessionmaker[Session])->Iterator[Session]:
	# 正常退出提交，异常退出回滚并关闭 Session，提交权不交给仓储。
	with session_factory.begin() as session:
		yield session


def dispose_database_engine(engine:Engine)->None:
	engine.dispose()
