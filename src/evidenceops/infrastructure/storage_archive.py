"""可校验的诊断档案备份和跨数据库导入；不执行来自备份的 SQL。"""
import base64
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy import DateTime,select,func,inspect
from cryptography.fernet import Fernet,InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from evidenceops.infrastructure.database.models import Base,UTCDateTime

MAX_ARCHIVE_BYTES=100*1024*1024

def canonical(value):
	return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")

def atomic_json(path,value):
	path=Path(path);temporary=path.with_name(path.name+".pending")
	try:
		with temporary.open("wb") as file:
			file.write(canonical(value));file.flush();os.fsync(file.fileno())
		if os.name!="nt": temporary.chmod(0o600)
		os.replace(temporary,path) # 保留旧文件直到新文件完整。
	finally:
		if temporary.exists(): temporary.unlink()

def portable_cipher(password,salt):
	if len(password)<12: raise ValueError("凭据备份口令至少需要 12 个字符")
	derived=PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=600000).derive(password.encode()) # 派生过程仅在服务器执行。
	return Fernet(base64.urlsafe_b64encode(derived))

def export_archive(engine,store,password=None):
	tables={}
	with engine.connect() as connection:
		for table in Base.metadata.sorted_tables:
			rows=[]
			available={column["name"] for column in inspect(connection).get_columns(table.name)}
			missing={column.name for column in table.columns}-available
			if missing and missing!={"model_config"}: raise ValueError("数据库结构不完整，无法生成完整备份") # 不伪造可恢复备份。
			for row in connection.execute(select(*[column for column in table.columns if column.name in available])).mappings():
				result={name:value.isoformat() if isinstance(value,datetime) else value for name,value in row.items()}
				for name in missing: result[name]=None
				rows.append(result)
			tables[table.name]=rows
	with store.lock,sqlite3.connect(store.path) as database:
		connections=[{"id":identity,"payload":json.loads(payload)} for identity,payload in database.execute("SELECT id,payload FROM connections")]
		default=json.loads(database.execute("SELECT value FROM settings WHERE id='default'").fetchone()[0])
		snapshots={identity:json.loads(payload) for identity,payload in database.execute("SELECT run_id,payload FROM snapshots")}
		secrets={identity:store.cipher.decrypt(secret).decode() for identity,secret in database.execute("SELECT id,secret FROM connections")} if password else None
	for row in tables["diagnosis_runs"]:
		if not row.get("model_config"): row["model_config"]=snapshots.get(row["run_id"])
	payload={"format":"evidenceops-archive-v1","schema":"0005","tables":tables,"connections":connections,"default":default,"snapshots":snapshots}
	if password:
		salt=os.urandom(16);cipher=portable_cipher(password,salt)
		payload["credentials"]={"salt":base64.b64encode(salt).decode(),"ciphertext":cipher.encrypt(canonical(secrets)).decode()}
	encoded=canonical(payload)
	if len(encoded)>MAX_ARCHIVE_BYTES: raise ValueError("备份超过当前 100 MB 限制，请使用管理员数据库备份")
	return {"payload":payload,"sha256":hashlib.sha256(encoded).hexdigest()}

def validate_archive(archive,password=None,allow_locked=False):
	if not isinstance(archive,dict) or set(archive)!={"payload","sha256"}: raise ValueError("备份格式无效")
	payload=archive["payload"]
	if not isinstance(payload,dict): raise ValueError("备份数据格式无效")
	encoded=canonical(payload)
	if len(encoded)>MAX_ARCHIVE_BYTES or hashlib.sha256(encoded).hexdigest()!=archive["sha256"]: raise ValueError("备份校验失败，文件可能已损坏")
	if payload.get("format")!="evidenceops-archive-v1" or payload.get("schema")!="0005": raise ValueError("备份版本不受支持")
	if not isinstance(payload.get("tables"),dict) or set(payload["tables"])!={table.name for table in Base.metadata.sorted_tables}: raise ValueError("备份数据表不完整")
	for table in Base.metadata.sorted_tables:
		if not isinstance(payload["tables"][table.name],list): raise ValueError("备份记录格式无效")
		for row in payload["tables"][table.name]:
			if not isinstance(row,dict) or set(row)!={column.name for column in table.columns}: raise ValueError("备份字段与当前版本不一致")
	connections=payload.get("connections");snapshots=payload.get("snapshots");default=payload.get("default")
	if not isinstance(connections,list) or len(connections)>100 or not isinstance(snapshots,dict): raise ValueError("模型连接备份格式无效")
	identities=set()
	for entry in connections:
		if not isinstance(entry,dict) or set(entry)!={"id","payload"} or not isinstance(entry["id"],str) or not isinstance(entry["payload"],dict): raise ValueError("模型连接记录格式无效")
		item=entry["payload"]
		if entry["id"] in identities or item.get("id")!=entry["id"] or any(not isinstance(item.get(field),str) or not item[field] for field in ("name","provider_id","protocol","endpoint","default_model")): raise ValueError("模型连接字段无效")
		if "api_key" in item or "secret" in item or not isinstance(item.get("config_version"),int) or not isinstance(item.get("timeout_seconds"),(int,float)): raise ValueError("模型连接配置无效")
		from urllib.parse import urlsplit
		endpoint=urlsplit(item["endpoint"])
		if endpoint.scheme not in ("http","https") or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment: raise ValueError("模型接口地址无效")
		identities.add(entry["id"])
	if default is not None and (not isinstance(default,dict) or set(default)!={"connection_id","model_id"} or default["connection_id"] not in identities|{"system"} or not isinstance(default["model_id"],str)): raise ValueError("默认连接引用无效")
	if any(not isinstance(identity,str) or not isinstance(snapshot,dict) for identity,snapshot in snapshots.items()): raise ValueError("运行模型快照格式无效")
	secrets={}
	if "credentials" in payload:
		block=payload["credentials"]
		if not isinstance(block,dict) or set(block)!={"salt","ciphertext"} or any(not isinstance(value,str) for value in block.values()): raise ValueError("凭据备份格式无效")
		if allow_locked and not password: return payload,secrets
		if not password: raise ValueError("此备份包含凭据，请填写备份口令")
		try:
			block=payload["credentials"];cipher=portable_cipher(password,base64.b64decode(block["salt"],validate=True))
			secrets=json.loads(cipher.decrypt(block["ciphertext"].encode()))
			if not isinstance(secrets,dict) or set(secrets)-identities or any(not isinstance(value,str) for value in secrets.values()): raise ValueError("凭据引用无效")
		except (InvalidToken,KeyError,ValueError,TypeError): raise ValueError("备份口令错误或凭据数据损坏") from None
	return payload,secrets

def import_tables(engine,payload):
	with engine.begin() as connection: # 任一表失败整体回滚。
		if any(connection.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables): raise ValueError("目标已有诊断数据，禁止覆盖或合并")
		for table in Base.metadata.sorted_tables:
			rows=[]
			for source in payload["tables"][table.name]:
				row=dict(source)
				for column in table.columns:
					if isinstance(column.type,(DateTime,UTCDateTime)) and row[column.name] is not None: row[column.name]=datetime.fromisoformat(row[column.name])
				rows.append(row)
			if rows: connection.execute(table.insert(),rows)
			actual=connection.scalar(select(func.count()).select_from(table))
			if actual!=len(rows): raise ValueError("恢复记录数量不一致")
		for table in Base.metadata.sorted_tables:
			actual=[{name:value.isoformat() if isinstance(value,datetime) else value for name,value in row.items()} for row in connection.execute(select(table)).mappings()]
			def normalized(row):
				row=dict(row)
				for column in table.columns:
					if isinstance(column.type,(DateTime,UTCDateTime)) and row[column.name]:
						from datetime import timezone
						date=datetime.fromisoformat(row[column.name]);row[column.name]=(date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)).isoformat()
				return canonical(row)
			if sorted(map(normalized,actual))!=sorted(map(normalized,payload["tables"][table.name])): raise ValueError("恢复内容校验不一致")
		if engine.dialect.name=="postgresql": # 显式导入主键后推进序列，防止下一次诊断撞号。
			from sqlalchemy import text
			connection.execute(text("SELECT setval(pg_get_serial_sequence('execution_records','record_id'),COALESCE((SELECT MAX(record_id) FROM execution_records),1),EXISTS(SELECT 1 FROM execution_records))"))

def restore_connections(store,payload,secrets):
	with store.transaction() as database:
		database.execute("DELETE FROM connections");database.execute("DELETE FROM snapshots")
		for entry in payload["connections"]:
			item=dict(entry["payload"]);secret=secrets.get(entry["id"],"")
			item["key_configured"]=bool(secret);item["status"]="stale";item["verified_at"]=None;item["validations"]={};item["catalog"]=None # 目标环境必须重新验证。
			database.execute("INSERT INTO connections VALUES (?,?,?)",(entry["id"],json.dumps(item),store.cipher.encrypt(secret.encode())))
		for identity,snapshot in payload["snapshots"].items(): database.execute("INSERT INTO snapshots VALUES (?,?)",(identity,json.dumps(snapshot)))
		database.execute("UPDATE settings SET value=? WHERE id='default'",(json.dumps(payload["default"]),))
