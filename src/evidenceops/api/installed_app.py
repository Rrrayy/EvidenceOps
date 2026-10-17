"""负责本机安装管理、存储检查、维护任务、备份恢复与诊断准入。"""
import asyncio
import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel,ConfigDict,Field,SecretStr
from starlette.responses import JSONResponse,FileResponse
from sqlalchemy import inspect,text,select
from evidenceops.infrastructure.local_storage import data_directory,FileLease,LocalPersistence
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.models import RunRow
from evidenceops.infrastructure.model_connections import ConnectionStore
from evidenceops.infrastructure.storage_archive import atomic_json,export_archive,validate_archive,import_tables,restore_connections,MAX_ARCHIVE_BYTES
from evidenceops.infrastructure.local_storage import migrate
from evidenceops.infrastructure.schema_versions import current_schema,database_schema,UnsupportedSchema

def utc_now(): return datetime.now(timezone.utc).isoformat()

class StorageInput(BaseModel):
	model_config=ConfigDict(extra="forbid")
	mode:str="sqlite"
	host:str=Field(default="127.0.0.1",min_length=1,max_length=253)
	port:int=Field(default=5433,ge=1,le=65535)
	database:str=Field(default="evidenceops",min_length=1,max_length=128)
	user:str=Field(default="evidenceops",min_length=1,max_length=128)
	password:SecretStr|None=None

class OperationInput(BaseModel):
	model_config=ConfigDict(extra="forbid")
	action:str
	expected_version:int=Field(ge=0)
	request_id:str=Field(min_length=8,max_length=100)
	storage:StorageInput|None=None
	backup_id:str|None=None
	passphrase:SecretStr|None=None
	confirmation:str|None=None

class StorageFailure(Exception):
	def __init__(self,state,message): self.state=state;self.message=message

class Installation:
	def __init__(self,root=None,factory=None):
		self.root=Path(root or data_directory()).resolve();self.factory=factory
		self.lease=FileLease(self.root/"installation.lock");self.child=None;self.child_lifespan=None
		self.store=None;self.token="";self.config={};self.operations={};self.backups={}
		self.state="initializing";self.message="正在准备本机存储";self.maintenance=False;self.active_requests=0;self.task=None
	def save_config(self): atomic_json(self.root/"storage.json",self.config)
	def save_operations(self): atomic_json(self.root/"operations.json",self.operations)
	def settings(self,value=None):
		value=(value or self.config["storage"]).copy()
		password=value.pop("password",None)
		if isinstance(password,SecretStr): password=password.get_secret_value()
		if value["mode"] not in ("sqlite","postgres"): raise StorageFailure("invalid","仅支持本机存储或 PostgreSQL")
		if value["mode"]=="sqlite" and self.config.get("storage",{}).get("mode")=="sqlite": value.setdefault("file",self.config["storage"].get("file","diagnosis.sqlite"))
		if value["mode"]=="postgres":
			if password: value["password_encrypted"]=self.store.cipher.encrypt(password.encode()).decode()
			elif not value.get("password_encrypted"): value["password_encrypted"]=self.config.get("storage",{}).get("password_encrypted")
			if not value.get("password_encrypted"): raise StorageFailure("invalid","请填写数据库密码")
		return value
	def engine(self,value):
		if value["mode"]=="sqlite":
			path=(self.root/value.get("file","diagnosis.sqlite")).resolve()
			if path.parent!=self.root or path.suffix!=".sqlite": raise StorageFailure("invalid","存储文件必须位于本安装的数据目录")
			return LocalPersistence(path)
		password=self.store.cipher.decrypt(value["password_encrypted"].encode()).decode()
		settings=DatabaseSettings(value["host"],value["port"],value["database"],value["user"],password)
		engine=create_database_engine(settings)
		return SqlAlchemyDiagnosisPersistence(create_session_factory(engine),engine)
	def prepare(self,value,initialize=False):
		store=self.engine(value)
		try:
			store.acquire_instance_lock()
			if value["mode"]=="postgres":
				with store._engine.connect() as connection:
					version=database_schema(connection)
					if version is None and inspect(connection).get_table_names(): raise StorageFailure("failed","目标数据库存在未受管理的表，请使用专用空数据库")
				if version!=current_schema():
					if not initialize: raise StorageFailure("needs_upgrade" if version else "uninitialized","数据库需要初始化或升级，请在存储设置中确认操作")
					if version: self.publish_archive(export_archive(store._engine,self.store),"数据库升级前备份",False)
					migrate(store._engine)
			with store._engine.connect() as connection:
				if database_schema(connection)!=current_schema(): raise StorageFailure("failed","迁移未达到当前版本，拒绝启动")
				connection.rollback()
				transaction=connection.begin()
				try:
					identity="storage-check-"+str(uuid4())
					connection.execute(RunRow.__table__.insert().values(run_id=identity,request_id=identity,description="storage-check",status="pending",created_at=datetime.now(timezone.utc)))
					if connection.scalar(select(RunRow.run_id).where(RunRow.run_id==identity))!=identity: raise StorageFailure("failed","存储读写检查失败")
				finally: transaction.rollback()
			return store
		except UnsupportedSchema as error:
			store.close()
			raise StorageFailure("unsupported_version",str(error)) from error
		except BaseException: store.close();raise
	async def start_child(self,persistence):
		if self.factory is None:
			from evidenceops.api.agent_app import build_configured_agent_app
			factory=build_configured_agent_app
		else: factory=self.factory
		try:
			child=factory(diagnosis_persistence=persistence,connection_store=self.store)
			context=child.router.lifespan_context(child)
			await context.__aenter__()
		except BaseException: persistence.close() if persistence else None;raise
		self.child=child;self.child_lifespan=context
	async def stop_child(self):
		context=self.child_lifespan;self.child=None;self.child_lifespan=None
		if context: await context.__aexit__(None,None,None)
	async def start(self):
		try:
			self.lease.acquire();self.root.mkdir(parents=True,exist_ok=True)
			self.token=secrets.token_urlsafe(32)
			tokenfile=self.root/"admin.token";tokenfile.write_text(self.token,encoding="utf-8")
			if os.name!="nt": tokenfile.chmod(0o600)
			self.store=ConnectionStore(os.getenv("EVIDENCEOPS_CONNECTIONS_DIR") or self.root/"model-connections")
			path=self.root/"storage.json"
			if path.exists(): self.config=json.loads(path.read_text(encoding="utf-8"))
			else:
				value={"mode":"postgres" if os.getenv("EVIDENCEOPS_PERSISTENCE")=="postgres" else "sqlite"}
				if value["mode"]=="postgres":
					settings=DatabaseSettings.from_environment();value.update(host=settings.host,port=settings.port,database=settings.database,user=settings.user,password=settings.password)
				self.config={"version":0,"setup_completed":False,"storage":self.settings(value)};self.save_config()
			journal=self.root/"maintenance.json" # 跨文件恢复过程以配置发布作为提交点。
			if journal.exists():
				pending=json.loads(journal.read_text(encoding="utf-8"))
				if self.config["version"]==pending["old_version"] and pending.get("connections_backup"): # 新存储未提交，恢复原模型配置。
					rollback=(self.root/pending["connections_backup"]).resolve()
					if rollback.parent!=self.root or not rollback.is_file(): raise StorageFailure("failed","维护恢复副本不存在或路径无效")
					with sqlite3.connect(rollback) as source,sqlite3.connect(self.store.path) as target:
						if source.execute("PRAGMA quick_check").fetchone()[0]!="ok" or not source.execute("SELECT 1 FROM settings WHERE id='default'").fetchone(): raise StorageFailure("failed","维护恢复副本无效，请检查备份")
						source.backup(target)
				journal.unlink()
			for filename,attribute in (("operations.json","operations"),("backups.json","backups")):
				path=self.root/filename
				if path.exists(): setattr(self,attribute,json.loads(path.read_text(encoding="utf-8")))
			for operation in self.operations.values():
				if operation["status"] in ("running","waiting"): operation.update(status="failed",message="上次维护被中断，请检查存储后重新操作",finished_at=utc_now())
			self.save_operations()
			await self.start_child(await asyncio.to_thread(self.prepare,self.config["storage"]))
			self.state="ready";self.message="诊断历史已开启"
		except Exception as error:
			self.state=error.state if isinstance(error,StorageFailure) else "failed";self.message=error.message if isinstance(error,StorageFailure) else "存储启动失败，请检查目录权限、数据库连接或版本"
			if self.store and self.child is None:
				try: await self.start_child(None)
				except Exception: pass
	async def close(self):
		if self.task and not self.task.done(): await self.task
		try: await self.stop_child()
		finally: self.lease.close()
	def status(self):
		value=self.config.get("storage",{});manager=self.child.state.connection_manager if self.child else None
		return {"supported":True,"state":"maintenance" if self.maintenance else self.state,"message":self.message,"mode":value.get("mode","sqlite"),"version":self.config.get("version",0),"setup_completed":self.config.get("setup_completed",False),"source_mode":"samples","schema_version":current_schema() if self.state=="ready" else None,"data_location":str(self.root),"database_display":f"{value.get('host')}:{value.get('port')} / {value.get('database')}" if value.get("mode")=="postgres" else str(self.root/value.get("file","diagnosis.sqlite")),"postgres":{"host":value.get("host","127.0.0.1"),"port":value.get("port",5433),"database":value.get("database","evidenceops"),"user":value.get("user","evidenceops"),"password_configured":bool(value.get("password_encrypted"))},"active_runs":sum(manager.store.active.values()) if manager else 0,"backups":list(self.backups.values()),"operations":list(self.operations.values())[-20:]}
	def publish_archive(self,archive,label,credentials,password=None):
		identity=str(uuid4());directory=self.root/"backups";directory.mkdir(exist_ok=True)
		path=directory/(identity+".json");atomic_json(path,archive)
		validate_archive(json.loads(path.read_text(encoding="utf-8")),password)
		record={"id":identity,"created_at":utc_now(),"label":label,"size_bytes":path.stat().st_size,"sha256":archive["sha256"],"credentials_included":credentials}
		self.backups[identity]=record;atomic_json(self.root/"backups.json",self.backups)
		return identity
	def backup(self,password=None,label="手动备份"):
		persistence=self.child.state.assembly.diagnosis_persistence if self.child else None
		if persistence is None: raise StorageFailure("failed","当前存储不可用，无法创建完整备份")
		archive=export_archive(persistence._engine,self.store,password)
		return self.publish_archive(archive,label,bool(password),password)
	async def submit(self,request):
		for operation in self.operations.values():
			if operation["request_id"]==request.request_id: return operation
		if self.maintenance: raise StorageFailure("busy","已有维护操作正在执行，请等待完成")
		if request.expected_version!=self.config.get("version",0): raise StorageFailure("conflict","存储配置已改变，请刷新后重试")
		if request.action not in ("initialize","switch","backup","restore","complete_setup"): raise StorageFailure("invalid","维护操作不受支持")
		if request.action=="restore" and request.confirmation!="恢复备份": raise StorageFailure("invalid","请确认恢复会替换当前诊断历史与模型连接")
		if not self.store or not self.config: raise StorageFailure("failed","数据目录尚未准备好，请先修复目录权限并重启")
		operation={"id":str(uuid4()),"request_id":request.request_id,"action":request.action,"status":"waiting","stage":"waiting","message":"等待当前诊断和验证完成","created_at":utc_now()}
		self.operations[operation["id"]]=operation;self.save_operations();self.maintenance=True
		self.task=asyncio.create_task(self.perform(operation,request))
		return operation
	async def perform(self,operation,request):
		old_config=json.loads(json.dumps(self.config));stopped=False;candidate=None;rollback_path=None
		def stage(name,message): operation.update(status="running",stage=name,message=message);self.save_operations()
		try:
			for attempt in range(1500):
				manager=self.child.state.connection_manager if self.child else None
				if self.active_requests==0 and (manager is None or (not any(manager.store.active.values()) and not manager.store.validating)): break # 包含断开观察的后台 Run。
				await asyncio.sleep(0.2)
			else: raise StorageFailure("busy","等待运行结束超时；本次维护未执行，请稍后重试")
			password=request.passphrase.get_secret_value() if request.passphrase else None
			if request.action=="complete_setup":
				if self.state!="ready": raise StorageFailure("failed","请先完成存储初始化")
				self.config["setup_completed"]=True;self.config["version"]+=1;self.save_config()
			elif request.action=="backup":
				stage("backup","正在备份并校验档案");operation["backup_id"]=await asyncio.to_thread(self.backup,password)
			else:
				payload=None;credentials={}
				if request.action=="restore":
					if request.backup_id not in self.backups: raise StorageFailure("invalid","备份不存在，请刷新备份列表")
					path=self.root/"backups"/(request.backup_id+".json")
					if path.stat().st_size>MAX_ARCHIVE_BYTES: raise StorageFailure("invalid","备份超过恢复大小限制")
					payload,credentials=await asyncio.to_thread(validate_archive,json.loads(path.read_text(encoding="utf-8")),password)
				value=self.settings(request.storage.model_dump() if request.storage else None)
				if request.action in ("switch","restore") and value["mode"]=="sqlite": value["file"]="diagnosis-"+str(uuid4())+".sqlite"
				current=self.child.state.assembly.diagnosis_persistence if self.child else None
				if current and self.state=="ready":
					stage("backup","正在创建维护前备份");operation["safety_backup_id"]=await asyncio.to_thread(self.backup,None,"维护前备份")
					if request.action=="switch": payload=(await asyncio.to_thread(export_archive,current._engine,self.store))["payload"]
				elif request.action=="switch": raise StorageFailure("failed","当前历史不可读取，禁止在未知数据状态下迁移")
				stage("prepare","正在准备目标存储");await self.stop_child();stopped=True
				candidate=await asyncio.to_thread(self.prepare,value,True)
				if payload:
					stage("copy","正在迁移并校验档案内容");await asyncio.to_thread(import_tables,candidate._engine,payload)
				if request.action=="restore":
					rollback_path=self.root/("connections-before-"+operation["id"]+".sqlite")
					with sqlite3.connect(self.store.path) as source,sqlite3.connect(rollback_path) as target: source.backup(target)
					atomic_json(self.root/"maintenance.json",{"old_version":old_config["version"],"connections_backup":rollback_path.name}) # 在修改连接前记录跨进程回滚依据。
					await asyncio.to_thread(restore_connections,self.store,payload,credentials)
				stage("activate","正在启动并检查诊断服务");await self.start_child(candidate);candidate=None
				self.config["storage"]=value;self.config["version"]+=1;self.save_config() # 成功就绪后才持久切换。
				self.state="ready";self.message="诊断历史已开启"
			operation.update(status="succeeded",stage="complete",message="操作已完成并通过校验",finished_at=utc_now())
			try: (self.root/"maintenance.json").unlink(missing_ok=True)
			except OSError: pass
		except Exception as error:
			if candidate: candidate.close()
			if stopped:
				await self.stop_child()
				if rollback_path and rollback_path.exists():
					with sqlite3.connect(rollback_path) as source,sqlite3.connect(self.store.path) as target: source.backup(target)
				self.config=old_config
				try: await self.start_child(await asyncio.to_thread(self.prepare,self.config["storage"]));self.state="ready";self.message="维护失败，原存储已恢复"
				except Exception:
					self.state="failed";self.message="维护未完成，请检查原存储；没有自动降级为内存模式"
					try: await self.start_child(None)
					except Exception: pass
			self.config=old_config
			if self.state=="ready": (self.root/"maintenance.json").unlink(missing_ok=True)
			operation.update(status="failed",stage="failed",message=error.message if isinstance(error,StorageFailure) else "维护失败，请检查存储连接、权限、空间或备份版本",finished_at=utc_now())
		finally: self.maintenance=False;self.save_operations()

class DiagnosisDispatch:
	def __init__(self,installation): self.installation=installation
	async def __call__(self,scope,receive,send):
		installation=self.installation;path=scope.get("path","");method=scope.get("method","GET")
		write=method not in ("GET","HEAD","OPTIONS") and not path.endswith("/cancel") # 维护期间允许显式取消。
		diagnosis="/diagnosis" in path or "/runs" in path
		if (write and installation.maintenance) or (diagnosis and installation.state!="ready"):
			await JSONResponse(status_code=503,content={"error_code":"STORAGE_NOT_READY","message":"存储尚未就绪或正在维护，请先完成存储设置"})(scope,receive,send);return
		if installation.child is None:
			await JSONResponse(status_code=503,content={"error_code":"SERVICE_NOT_READY","message":"诊断服务尚未准备好，请查看数据与存储"})(scope,receive,send);return
		if write: installation.active_requests+=1
		try: await installation.child(scope,receive,send)
		finally:
			if write: installation.active_requests-=1

def create_installed_app(root=None,factory=None):
	installation=Installation(root,factory)
	@asynccontextmanager
	async def lifespan(app):
		await installation.start()
		try: yield
		finally: await installation.close()
	app=FastAPI(lifespan=lifespan);app.state.installation=installation
	@app.exception_handler(RequestValidationError)
	async def invalid(request,error): return JSONResponse(status_code=422,content={"message":"请检查必填字段、类型与长度"})
	@app.exception_handler(StorageFailure)
	async def failure(request,error): return JSONResponse(status_code=409 if error.state in ("busy","conflict") else 422,content={"error_code":error.state,"message":error.message})
	@app.middleware("http")
	async def local_guard(request,call_next): # 当前交付严格限制为本机安装，不宣传远程多人平台。
		if request.client.host not in ("127.0.0.1","::1","testclient") or request.url.hostname not in ("127.0.0.1","localhost","::1","testserver"): return JSONResponse(status_code=403,content={"message":"安装管理仅允许本机访问"})
		if request.method not in ("GET","HEAD","OPTIONS") and request.url.path.startswith("/api/v1/agent/storage"):
			if request.headers.get("sec-fetch-site")=="cross-site" or not installation.token or not secrets.compare_digest(request.headers.get("x-evidenceops-admin",""),installation.token): return JSONResponse(status_code=403,content={"message":"维护请求未获本机授权"})
		return await call_next(request)
	@app.get("/api/v1/agent/storage/status")
	@app.get("/api/v1/agent/setup/status")
	async def status():
		if installation.state=="ready" and not installation.maintenance and installation.child:
			try:
				def probe():
					with installation.child.state.assembly.diagnosis_persistence.transaction() as transaction: transaction.run.list_recent(1)
				await asyncio.to_thread(probe)
			except Exception: installation.state="degraded";installation.message="存储检查失败，新诊断已暂停，请检查连接并重新初始化"
		return installation.status()
	@app.get("/api/v1/agent/capabilities")
	async def capabilities():
		ready=installation.state=="ready" and not installation.maintenance
		assembly=installation.child.state.assembly if installation.child else None
		knowledge=bool(ready and assembly and any(getattr(tool,"name",None)=="search_knowledge" for tool in assembly.tools))
		parsed_tool=next((tool for tool in assembly.tools if getattr(tool,"name",None)=="query_parsed_logs"),None) if ready and assembly else None
		return {"persistence":ready,"storage_management":True,"storage_state":"maintenance" if installation.maintenance else installation.state,
			"parsed_logs":parsed_tool is not None,"parsed_log_sources":parsed_tool.parameters_schema["properties"]["source_id"]["enum"] if parsed_tool else [],
			"source_mode":"samples","input":"description","knowledge_search":knowledge,
			"sources":["log","metric","config"]+(["knowledge"] if knowledge else []),"model_connections":installation.child is not None,
			"provider_mode":"mock" if assembly is None or assembly.provider_name=="mock" else "configured"}
	@app.post("/api/v1/agent/storage/check")
	async def check(value:StorageInput):
		settings=installation.settings(value.model_dump())
		if settings["mode"]=="sqlite": return {"connected":True,"message":"本机存储会在安装数据目录创建，初始化后检查真实读写能力"}
		def inspect_target():
			store=installation.engine(settings)
			try:
				with store._engine.connect() as connection:
					connection.execute(text("SELECT 1"));version=connection.scalar(text("SELECT version_num FROM alembic_version")) if inspect(connection).has_table("alembic_version") else None
				return {"connected":True,"schema_version":version,"message":"连接成功；初始化与业务写入权限将在维护操作中验证"}
			finally: store.close()
		try: return await asyncio.to_thread(inspect_target)
		except Exception: return JSONResponse(status_code=422,content={"message":"数据库连接失败，请检查地址、账号、密码或服务状态"})
	@app.post("/api/v1/agent/storage/operations",status_code=202)
	async def operation(value:OperationInput): return await installation.submit(value)
	@app.get("/api/v1/agent/storage/operations/{identity}")
	async def operation_status(identity:str):
		if identity not in installation.operations: return JSONResponse(status_code=404,content={"message":"维护操作不存在"})
		return installation.operations[identity]
	@app.get("/api/v1/agent/storage/backups/{identity}")
	async def download(identity:str):
		if identity not in installation.backups: return JSONResponse(status_code=404,content={"message":"备份不存在"})
		return FileResponse(installation.root/"backups"/(identity+".json"),filename="evidenceops-backup-"+identity+".json",media_type="application/json")
	@app.post("/api/v1/agent/storage/backups/import")
	async def import_backup(request:Request):
		if installation.maintenance: raise StorageFailure("busy","维护进行中，请等待后再导入")
		chunks=bytearray()
		async for chunk in request.stream():
			chunks.extend(chunk)
			if len(chunks)>MAX_ARCHIVE_BYTES: return JSONResponse(status_code=413,content={"message":"备份不能超过 100 MB"})
		try:
			archive=json.loads(chunks);payload,_=validate_archive(archive,allow_locked=True)
			identity=str(uuid4());directory=installation.root/"backups";directory.mkdir(exist_ok=True)
			path=directory/(identity+".json");atomic_json(path,archive)
			record={"id":identity,"created_at":utc_now(),"label":"导入备份","size_bytes":path.stat().st_size,"sha256":archive["sha256"],"credentials_included":"credentials" in payload}
			installation.backups[identity]=record;atomic_json(installation.root/"backups.json",installation.backups)
			return record
		except (ValueError,KeyError,TypeError): return JSONResponse(status_code=422,content={"message":"备份格式或内容校验失败"})
	app.mount("/",DiagnosisDispatch(installation))
	return app

app=create_installed_app()
