"""本机模型连接配置库：密钥加密，版本检查与运行快照独立持久化。"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4
from cryptography.fernet import Fernet

class ConnectionError(ValueError):
	def __init__(self,message,code="INVALID_CONNECTION",status=422):
		super().__init__(message);self.code=code;self.status=status

def now():
	return datetime.now(timezone.utc).isoformat()

def validate_endpoint(value):
	parsed=urlsplit(value.strip())
	allowed={host.strip().lower() for host in os.getenv("EVIDENCEOPS_MODEL_ALLOWED_HOSTS","maas.qianwenaiapi.com,dashscope.aliyuncs.com").split(",") if host.strip()}
	if parsed.scheme not in ("https","http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
		raise ConnectionError("接口地址必须是 HTTP(S) 地址，且不能包含用户名、密码、查询参数或片段")
	if parsed.hostname.lower() not in allowed:
		raise ConnectionError("此服务主机未获允许；请在后端 EVIDENCEOPS_MODEL_ALLOWED_HOSTS 中添加主机名")
	if parsed.scheme=="http" and os.getenv("EVIDENCEOPS_MODEL_ALLOW_HTTP")!="1":
		raise ConnectionError("默认仅允许 HTTPS；内部 HTTP 服务需后端显式启用")
	try: parsed.port
	except ValueError: raise ConnectionError("接口端口格式无效") from None
	return value.strip().rstrip("/")

class ConnectionStore:
	def __init__(self,directory=None,key=None):
		self.directory=Path(directory or os.getenv("EVIDENCEOPS_CONNECTIONS_DIR","output/model-connections"))
		self.directory.mkdir(parents=True,exist_ok=True)
		self.path=self.directory/"connections.db"
		self.lock=RLock();self.active={};self.validating=set()
		secret=key or os.getenv("EVIDENCEOPS_CONNECTIONS_KEY")
		keyfile=self.directory/"credentials.key"
		if not secret:
			try:
				if os.name!="nt":
					with keyfile.open("xb") as file: file.write(Fernet.generate_key())
			except FileExistsError: pass
			if os.name=="nt":
				import ctypes
				from ctypes import wintypes
				class Blob(ctypes.Structure):
					_fields_=[("size",wintypes.DWORD),("data",ctypes.POINTER(ctypes.c_byte))]
				def protect(data,decrypt=False):
					buffer=ctypes.create_string_buffer(data);incoming=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)));outgoing=Blob()
					function=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData # DPAPI 用户作用域。
					if not function(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing)): raise RuntimeError("本机凭据保护失败")
					try: return ctypes.string_at(outgoing.data,outgoing.size)
					finally: ctypes.windll.kernel32.LocalFree(outgoing.data)
				with self.lock:
					if not keyfile.exists():
						try:
							with keyfile.open("xb") as file: file.write(b"DPAPI:"+protect(Fernet.generate_key()))
						except FileExistsError: pass
					data=keyfile.read_bytes()
					if not data.startswith(b"DPAPI:"):
						data=b"DPAPI:"+protect(data);keyfile.write_bytes(data)
					secret=protect(data[6:],True)
			else:
				keyfile.chmod(0o600);secret=keyfile.read_bytes()
		self.cipher=Fernet(secret.encode() if isinstance(secret,str) else secret)
		with self.transaction() as database:
			database.execute("CREATE TABLE IF NOT EXISTS connections (id TEXT PRIMARY KEY, payload TEXT NOT NULL, secret BLOB NOT NULL)")
			database.execute("CREATE TABLE IF NOT EXISTS settings (id TEXT PRIMARY KEY, value TEXT)")
			database.execute("CREATE TABLE IF NOT EXISTS snapshots (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
			database.execute("INSERT OR IGNORE INTO settings VALUES ('default','null')")

	@contextmanager
	def transaction(self):
		with self.lock,sqlite3.connect(self.path,timeout=5) as database:
			database.row_factory=sqlite3.Row;database.execute("BEGIN IMMEDIATE")
			yield database

	def _row(self,database,identity):
		row=database.execute("SELECT * FROM connections WHERE id=?",(identity,)).fetchone()
		if row is None: raise ConnectionError("模型连接不存在","CONNECTION_NOT_FOUND",404)
		return json.loads(row["payload"]),row["secret"]

	def public(self,item,default=None):
		fields=("id","name","provider_id","protocol","default_model","timeout_seconds","context_window_tokens","max_output_tokens","safety_margin_tokens","max_run_tokens","limits_source","limits_verified_at","config_version","status","verified_at","updated_at","validations","catalog")
		result={field:item.get(field) for field in fields}
		parsed=urlsplit(item["endpoint"]);result["endpoint_display"]=f"{parsed.scheme}://{parsed.netloc}"
		result["editable"]=True;result["key_configured"]=item.get("key_configured",True);result["is_default"]=bool(default and default["connection_id"]==item["id"]) # 无凭据备份恢复后要求重新填钥。
		return result

	def listing(self):
		with self.transaction() as database:
			default=json.loads(database.execute("SELECT value FROM settings WHERE id='default'").fetchone()[0])
			return {"items":[self.public(json.loads(row[0]),default) for row in database.execute("SELECT payload FROM connections ORDER BY rowid DESC")],"default":default}

	def save(self,data,identity=None):
		with self.transaction() as database:
			if identity:
				item,secret=self._row(database,identity)
				if data.get("expected_version")!=item["config_version"]: raise ConnectionError("配置已更新，请重新打开编辑","CONFIG_CONFLICT",409)
			else:
				if database.execute("SELECT count(*) FROM connections").fetchone()[0]>=100: raise ConnectionError("模型连接最多保存100个")
				item={"id":f"conn-{uuid4()}","config_version":0,"validations":{},"catalog":None,"verified_at":None,"status":"unverified"};secret=None
			before={field:item.get(field) for field in ("provider_id","protocol","endpoint","default_model","timeout_seconds")}
			for field in ("name","provider_id","protocol","default_model","timeout_seconds","context_window_tokens","max_output_tokens","safety_margin_tokens","max_run_tokens","limits_source","limits_verified_at"):
				if field in data: item[field]=data[field]
			from evidenceops.application.token_budget import ContextConfig
			try:
				context=ContextConfig(context_window_tokens=item.get("context_window_tokens",32768),max_output_tokens=item.get("max_output_tokens",2048),safety_margin_tokens=item.get("safety_margin_tokens",256),max_run_tokens=item.get("max_run_tokens",16384),limits_source=item.get("limits_source","legacy_compatibility"),limits_verified_at=item.get("limits_verified_at"))
			except (TypeError,ValueError) as error: raise ConnectionError(str(error)) from error
			item.update(context.to_dict())
			if not identity or data.get("endpoint"): item["endpoint"]=validate_endpoint(data.get("endpoint",""))
			if item.get("protocol")!="chat_completions" or item.get("provider_id") not in ("qianwen","custom"): raise ConnectionError("供应商或协议暂不支持")
			api_key=data.get("api_key")
			if api_key:
				item["key_configured"]=True # 补回密钥后恢复明确配置状态。
				if set(api_key.strip())<={"*","•","●"}: raise ConnectionError("请填写真实 API Key，不能提交密钥掩码")
				secret=self.cipher.encrypt(api_key.strip().encode())
			if secret is None: raise ConnectionError("请填写 API Key")
			changed=bool(api_key) or any(item.get(field)!=value for field,value in before.items()) # 名称变化不破坏模型能力。
			if changed: item.update(status="stale" if identity else "unverified",validations={},catalog=None,verified_at=None)
			item["config_version"]+=1;item["updated_at"]=now()
			if not changed:
				for result in item["validations"].values(): result["config_version"]=item["config_version"]
				if item["catalog"]: item["catalog"]["config_version"]=item["config_version"]
			database.execute("INSERT OR REPLACE INTO connections VALUES (?,?,?)",(item["id"],json.dumps(item),secret))
			return self.public(item)

	def credentials(self,identity,version=None):
		with self.transaction() as database:
			item,secret=self._row(database,identity)
			if version is not None and version!=item["config_version"]: raise ConnectionError("配置已修改，请重新读取","CONFIG_CONFLICT",409)
			return item,self.cipher.decrypt(secret).decode()

	def update_result(self,identity,version,field,value,model=None):
		with self.transaction() as database:
			item,secret=self._row(database,identity)
			if item["config_version"]!=version: raise ConnectionError("配置已修改，旧结果已丢弃","CONFIG_CONFLICT",409) # 不覆盖新配置。
			if field=="catalog": item["catalog"]=value
			else:
				item["validations"][model]=value;item["verified_at"]=value["verified_at"]
				if model==item["default_model"]: item["status"]=value["status"]
			database.execute("UPDATE connections SET payload=? WHERE id=?",(json.dumps(item),identity))
			return self.public(item)

	def set_default(self,identity,model,version=None):
		with self.transaction() as database:
			if identity=="system": value={"connection_id":"system","model_id":model}
			elif identity:
				item,_=self._row(database,identity)
				if version!=item["config_version"]: raise ConnectionError("配置已修改，请刷新","CONFIG_CONFLICT",409)
				value={"connection_id":identity,"model_id":model or item["default_model"]}
			else: value=None
			database.execute("UPDATE settings SET value=? WHERE id='default'",(json.dumps(value),))
			return value

	def delete(self,identity,version,replacement=None):
		with self.transaction() as database:
			item,_=self._row(database,identity)
			if version!=item["config_version"]: raise ConnectionError("配置已修改，请刷新","CONFIG_CONFLICT",409)
			if self.active.get(identity): raise ConnectionError("连接正在被诊断使用，请等待运行结束","CONNECTION_IN_USE",409) # 不取消诊断。
			default=json.loads(database.execute("SELECT value FROM settings WHERE id='default'").fetchone()[0])
			if default and default["connection_id"]==identity:
				if replacement and replacement!=identity:
					other,_=self._row(database,replacement);default={"connection_id":replacement,"model_id":other["default_model"]}
				elif replacement==identity: raise ConnectionError("替代连接不能是即将删除的连接")
				else: default=None
				database.execute("UPDATE settings SET value=? WHERE id='default'",(json.dumps(default),))
			database.execute("DELETE FROM connections WHERE id=?",(identity,))

	def snapshot(self,run_id,value=None):
		with self.transaction() as database:
			if value is not None: database.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?)",(run_id,json.dumps(value)))
			row=database.execute("SELECT payload FROM snapshots WHERE run_id=?",(run_id,)).fetchone()
			return json.loads(row[0]) if row else None
