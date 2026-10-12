"""本机持久化的目录、互斥锁、迁移及数据库工厂。"""
import os
from pathlib import Path
from sqlalchemy import create_engine,event
from alembic import command
from alembic.config import Config
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.session import create_session_factory

def data_directory():
	if os.getenv("EVIDENCEOPS_DATA_DIR"): return Path(os.environ["EVIDENCEOPS_DATA_DIR"]).expanduser().resolve()
	if os.name=="nt": return Path(os.environ.get("LOCALAPPDATA",str(Path.home()/"AppData"/"Local")))/"EvidenceOps"
	return Path(os.environ.get("XDG_DATA_HOME",str(Path.home()/".local"/"share")))/"evidenceops"

class FileLease:
	def __init__(self,path): self.path=Path(path);self.file=None
	def acquire(self):
		if self.file is not None: return
		self.path.parent.mkdir(parents=True,exist_ok=True)
		file=self.path.open("a+b")
		try:
			if file.seek(0,2)==0: file.write(b"0");file.flush()
			file.seek(0)
			if os.name=="nt":
				import msvcrt
				msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1) # 第二个实例立即拒绝。
			else:
				import fcntl
				fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB) # 排他非阻塞。
		except BaseException: file.close();raise RuntimeError("另一个 EvidenceOps 实例正在使用此数据目录") from None
		self.file=file
	def close(self):
		if self.file is not None: self.file.close();self.file=None

def sqlite_engine(path):
	engine=create_engine("sqlite:///"+str(Path(path).resolve()),connect_args={"check_same_thread":False,"timeout":5})
	@event.listens_for(engine,"connect")
	def configure(connection,record):
		connection.execute("PRAGMA foreign_keys=ON")
		connection.execute("PRAGMA busy_timeout=5000")
		connection.execute("PRAGMA journal_mode=WAL")
		connection.execute("PRAGMA synchronous=FULL")
	return engine

def migrate(engine):
	root=Path(__file__).resolve().parents[3]
	config=Config(str(root/"alembic.ini"))
	config.set_main_option("script_location",str(root/"alembic"))
	with engine.begin() as connection:
		config.attributes["connection"]=connection
		command.upgrade(config,"head") # 版本检查由 Alembic 执行。

class LocalPersistence(SqlAlchemyDiagnosisPersistence):
	def __init__(self,path):
		self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
		self.lease=FileLease(str(self.path)+".lock")
		engine=sqlite_engine(self.path)
		super().__init__(create_session_factory(engine),engine)
	def acquire_instance_lock(self):
		self.lease.acquire()
		try:
			import sqlite3
			from datetime import datetime,timezone
			if self.path.exists() and self.path.stat().st_size>0:
				with sqlite3.connect(self.path) as source:
					version=source.execute("SELECT version_num FROM alembic_version").fetchone() if source.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone() else None
					if version is None and source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone(): raise ValueError("数据库存在未受管理的表，禁止自动初始化")
					if version and version[0]!="0005":
						backup=self.path.with_name("pre-upgrade-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")+".sqlite")
						with sqlite3.connect(backup) as target: source.backup(target) # 包含已提交 WAL 数据。
			migrate(self._engine)
		except BaseException: self.lease.close();raise
	def close(self):
		try: super().close()
		finally: self.lease.close()
