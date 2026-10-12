"""模型连接 API：供应商请求由本机后端执行，默认无付费自动验证。"""
import json # 校验真实模型返回的报告结构。
from dataclasses import replace # 请求与结果不共享可变默认配置。
from threading import BoundedSemaphore # 限制验证与目录并发。
from uuid import uuid4 # 请求身份与运行身份独立。
import httpx # 受控服务端 HTTP 客户端。
from fastapi import Request # 检查浏览器跨站写请求。
from pydantic import BaseModel,Field,ConfigDict,field_validator # 禁止未声明字段进入连接配置。
from evidenceops.infrastructure.model_connections import ConnectionStore,ConnectionError,validate_endpoint,now # 密钥与快照持久化边界。
from evidenceops.infrastructure.providers.openai_compatible_provider import OpenAICompatibleProvider # 复用真实 Chat Completions 解析器。
from evidenceops.infrastructure.providers.mock_provider import MockProvider # 系统 Mock 显式标记。
from evidenceops.application.model_protocol import ModelRequest,ToolCall,ToolCallBatch,ModelProviderError # 检查真实工具协议。
from evidenceops.application.diagnosis_draft import DiagnosisDraft # 使用项目报告校验，不只校验 JSON。
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly # 每次运行独立组装，不修改共享 Provider。

class ConnectionInput(BaseModel): # 创建与更新明确字段白名单。
	model_config=ConfigDict(extra="forbid") # 禁止客户端指定验证通过状态。
	name:str=Field(min_length=1,max_length=80) # 用户名称。
	provider_id:str="custom" # 与协议分开表达。
	protocol:str="chat_completions" # 当前仅此协议。
	endpoint:str|None=Field(default=None,max_length=2048) # 编辑留空保留原地址。
	default_model:str=Field(min_length=1,max_length=200) # 模型 ID 可手填。
	timeout_seconds:float=Field(default=60,ge=1,le=300) # Provider 实际支持参数。
	api_key:str|None=Field(default=None,max_length=4096,repr=False) # 不出现在模型 repr。
	expected_version:int|None=None # 乐观并发版本。
	@field_validator("name","default_model")
	@classmethod
	def nonempty(cls,value): # 全空白不能作为连接名称或模型身份。
		if not value.strip(): raise ValueError("字段不能为空") # 校验异常由安全处理器转换。
		return value.strip() # 不改变密钥的输入语义。

class VersionInput(BaseModel): # 版本绑定长请求。
	model_config=ConfigDict(extra="forbid") # 不接收任意供应商参数。
	expected_version:int # 目录与验证使用同一配置。
	model_id:str|None=Field(default=None,min_length=1,max_length=200) # 允许验证其他模型。

class DefaultInput(BaseModel): # 默认行为独立于保存。
	model_config=ConfigDict(extra="forbid") # 默认写入不收集密钥。
	connection_id:str|None=None # null 表示无默认。
	model_id:str|None=Field(default=None,min_length=1,max_length=200) # 默认模型。
	expected_version:int|None=None # 防止设置陈旧配置。

class DeleteInput(BaseModel): # 删除包含明确替代决定。
	model_config=ConfigDict(extra="forbid") # 未知字段拒绝。
	expected_version:int # 用户确认的是这个版本。
	replacement_id:str|None=None # null 明确进入无默认状态。

class ConnectionManager: # 统一请求与 Run 生命周期。
	def __init__(self,assembly,store=None,client_factory=None): # 测试注入确定性 Transport。
		self.assembly=assembly;self.store=store or ConnectionStore() # 不访问模型供应商直到显式操作。
		self.custom_client=client_factory is not None # 测试 Transport 不绕过注入客户端。
		self.client_factory=client_factory or (lambda:httpx.Client(trust_env=False,follow_redirects=False)) # 不受环境代理和重定向影响。
		self.slots=BoundedSemaphore(4);self.running={} # 全局限制网络操作并记录取消目标。

	def system(self): # 环境提供配置作为只读系统连接。
		mock=isinstance(self.assembly.provider,MockProvider) # 系统是否真实模型。
		return {"id":"system","name":"系统连接（Mock 演示）" if mock else "系统连接","provider_id":self.assembly.provider_name,"protocol":"mock" if mock else "chat_completions","default_model":self.assembly.model,"status":"ready","config_version":0,"editable":False,"is_system":True,"mock":mock} # 没有环境密钥。

	def services(self): # 项目已有千问服务，区域不猜测。
		return {"items":[{"id":"qianwen","name":"千问（项目当前服务）","protocol":"chat_completions","endpoint":"https://maas.qianwenaiapi.com/compatible-mode/v1","region":None,"recommended_models":["qwen3.8-flash"]},{"id":"custom","name":"自定义兼容服务","protocol":"chat_completions","endpoint":"","region":None,"recommended_models":[]}]} # 推荐来自 environment.md，不代表账号权限。

	def _http(self,client,method,endpoint,key,timeout,body=None): # 统一安全错误分类，绝不回传供应商响应原文。
		validate_endpoint(endpoint) # 每次出站再次检查管理员白名单。
		try: response=client.request(method,endpoint,headers={"Authorization":f"Bearer {key}"},json=body,timeout=timeout) # 密钥仅请求头。
		except httpx.TimeoutException: raise ConnectionError("验证请求超时，请检查服务或增加超时","MODEL_TIMEOUT",504) from None # 去除潜在凭据异常。
		except httpx.RequestError: raise ConnectionError("模型服务暂时无法连接","MODEL_UNAVAILABLE",503) from None # 不输出 URL。
		if response.status_code==401: raise ConnectionError("认证失败，请检查 API Key","MODEL_AUTH_FAILED",422)
		if response.status_code==403: raise ConnectionError("当前账号无权访问指定模型","MODEL_ACCESS_DENIED",422) # 明确认证/权限边界。
		if response.status_code==404: raise ConnectionError("模型或接口不存在，或服务不支持此操作","MODEL_NOT_FOUND",422) # 模型/目录分别在调用层说明。
		if response.status_code==429 or response.status_code>=500: raise ConnectionError("模型服务暂时不可用或已限流","MODEL_UNAVAILABLE",503) # 可重试但不自动付费重试。
		if not 200<=response.status_code<300: raise ConnectionError("服务拒绝此模型调用或协议参数","MODEL_REQUEST_REJECTED",422) # 不泄露原文。
		if len(response.content)>2_000_000: raise ConnectionError("模型响应超过允许大小","MODEL_PROTOCOL_ERROR",422) # 控制读取解析资源。
		try: return response.json() # 正常返回实际 JSON。
		except ValueError: raise ConnectionError("模型服务返回无效 JSON","MODEL_PROTOCOL_ERROR",422) from None # 不输出正文。

	def catalog(self,identity,version): # 只在用户刷新时请求目录。
		item,key=self.store.credentials(identity,version) # 固定凭据与地址。
		if not self.slots.acquire(blocking=False): raise ConnectionError("模型请求较多，请稍后重试","MODEL_BUSY",429) # 避免无限并发。
		try: # 网络不持有数据库事务。
			with self.client_factory() as client: # 确保释放连接。
				try: # 目录不支持与失败分开呈现。
					payload=self._http(client,"GET",item["endpoint"]+"/models",key,item["timeout_seconds"]) # 固定允许路径。
					if not isinstance(payload,dict) or not isinstance(payload.get("data"),list): raise ConnectionError("模型目录格式无效","MODEL_PROTOCOL_ERROR",422) # 不能当空列表。
					identities=list(dict.fromkeys(row["id"] for row in payload["data"] if isinstance(row,dict) and isinstance(row.get("id"),str) and 0<len(row["id"])<=200))[:1000] # 去重并限定数量。
					result={"status":"ready" if identities else "empty","items":[{"id":model,"source":"catalog"} for model in identities],"updated_at":now(),"config_version":version} # 空列表有独立状态。
				except ConnectionError as error: result={"status":"unsupported" if error.code=="MODEL_NOT_FOUND" else "failed","items":[],"message":str(error),"updated_at":now(),"config_version":version} # 错误保留手填通道。
			self.store.update_result(identity,version,"catalog",result) # 旧目录不能写入新版配置。
			return result # 状态由实际请求决定。
		finally: self.slots.release() # 所有失败释放限流槽。

	def validate(self,identity,version,model=None): # 一次显式验证最多三个实际模型调用。
		item,key=self.store.credentials(identity,version);model=model or item["default_model"] # 同一配置快照。
		lease=(identity,version,model) # 防止重复付费点击。
		with self.store.lock: # 验证租约原子登记。
			if lease in self.store.validating: raise ConnectionError("该模型正在验证，请等待","VALIDATION_BUSY",409) # 重复请求不调用供应商。
			if not self.slots.acquire(blocking=False): raise ConnectionError("模型请求较多，请稍后重试","MODEL_BUSY",429) # 有界全局请求。
			self.store.validating.add(lease) # 长请求不锁数据库。
		checks=[{"name":name,"status":"pending"} for name in ("认证与连接","指定模型调用","工具调用及结果关联","结构化报告输出")] # 每项真实验证。
		try: # 错误保存为未就绪结果。
			with self.client_factory() as client: # 复用验证请求连接。
				base={"model":model,"max_tokens":1024} # 控制验证输出规模。
				first=self._http(client,"POST",item["endpoint"]+"/chat/completions",key,item["timeout_seconds"],{**base,"messages":[{"role":"user","content":"Reply with OK only."}]}) # 认证和指定模型调用真实验证。
				checks[0]["status"]="passed" # HTTP 认证接纳。
				OpenAICompatibleProvider._parse_response(first,ModelRequest((),(),model,item["timeout_seconds"],"validation","validation")) # 使用现有协议解析器。
				checks[1]["status"]="passed" # 指定模型响应可解析。
				tool={"type":"function","function":{"name":"evidenceops_probe","description":"Return a known evidence marker for validation.","parameters":{"type":"object","properties":{},"additionalProperties":False}}} # 无实际业务操作的探针。
				messages=[{"role":"user","content":"Call evidenceops_probe once before writing a report."}] # 请求工具调用。
				payload=self._http(client,"POST",item["endpoint"]+"/chat/completions",key,item["timeout_seconds"],{**base,"messages":messages,"tools":[tool]}) # 与实际 Agent 一致，不额外要求供应商支持强制工具选择；仍严格检查实际工具响应。
				parsed=OpenAICompatibleProvider._parse_response(payload,ModelRequest((),(tool,),model,item["timeout_seconds"],"validation","validation")) # 检查工具 ID 及参数。
				calls=parsed.response.calls if isinstance(parsed.response,ToolCallBatch) else (parsed.response,) # 支持单工具或批次。
				if len(calls)!=1 or not isinstance(calls[0],ToolCall) or calls[0].tool_name!="evidenceops_probe" or calls[0].arguments!={}: raise ConnectionError("模型未按要求调用验证工具","TOOLS_UNSUPPORTED",422) # 文本回复不是工具通过。
				call=calls[0] # 关联真实返回的工具调用 ID。
				messages+=[{"role":"assistant","content":None,"tool_calls":[{"id":call.tool_call_id,"type":"function","function":{"name":call.tool_name,"arguments":"{}"}}]},{"role":"tool","tool_call_id":call.tool_call_id,"content":'{"evidence_id":"validation-evidence","marker":"evidenceops-validation-checked"}'},{"role":"user","content":"Use the tool marker as root_cause.text, cite validation-evidence only. Return JSON with root_cause:{text,evidence_ids}, recommendations:[{text,evidence_ids}], confidence:0..1, limitations:nonempty string."}] # 工具消息保留结果关联。
				report=self._http(client,"POST",item["endpoint"]+"/chat/completions",key,item["timeout_seconds"],{**base,"messages":messages,"response_format":{"type":"json_object"}}) # 项目要求结构化报告。
				content=report["choices"][0]["message"]["content"];draft=DiagnosisDraft.from_mapping(json.loads(content)) # 完整项目草稿校验。
				if draft.root_cause.text!="evidenceops-validation-checked" or any(claim.evidence_ids!=("validation-evidence",) for claim in (draft.root_cause,*draft.recommendations)): raise ConnectionError("模型未正确关联工具结果或引用证据","TOOLS_UNSUPPORTED",422) # 不只看有 tool_calls 字段。
				checks[2]["status"]="passed";checks[3]["status"]="passed" # 完整结果关联和报告能力。
			result={"status":"ready","checks":checks,"verified_at":now(),"config_version":version,"model_id":model,"actual_model_id":report.get("model",model)} # 实际服务返回模型可追溯。
		except (ConnectionError,ModelProviderError,ValueError,TypeError,KeyError,IndexError) as error: # 无效结构也是未就绪。
			code=getattr(error,"code",getattr(error,"error_code","STRUCTURED_REPORT_UNSUPPORTED")) # 稳定错误类别。
			message=str(error) if isinstance(error,ConnectionError) else "模型输出未满足工具关联或结构化报告要求" # 不回传原始解析异常。
			for check in checks: # 未执行项区别于失败项。
				if check["status"]=="pending": check.update(status="failed",message=message);break # 首个未通过项有原因。
			result={"status":"partial" if checks[1]["status"]=="passed" else "failed","checks":checks,"verified_at":now(),"config_version":version,"model_id":model,"error_code":code,"message":message} # 连接通过不代表 Agent ready。
		finally: # 清理无论成功或失败。
			with self.store.lock: self.store.validating.discard(lease) # 不遗留验证中。
			self.slots.release() # 释放请求槽。
		self.store.update_result(identity,version,"validation",result,model) # 旧响应 CAS 丢弃。
		return result # 返回当时配置版本。

	def choose(self,identity=None,model=None,version=None): # 原子固定本次连接，不改全局默认。
		with self.store.lock: # 与删除和修改协调租约。
			if identity is None: # 兼容原有诊断请求。
				default=self.store.listing()["default"] # 未选择时使用用户默认或系统。
				identity=default["connection_id"] if default else "system";model=model or (default["model_id"] if default else None) # 不改前端历史展示。
			if identity=="system": # 系统配置只读，模型不能被手动替换。
				if model and model!=self.assembly.model: raise ConnectionError("系统连接仅支持后端配置的模型") # 不绕过能力校验。
				item=self.system();model=self.assembly.model;key=None # 无环境凭据回显。
			else: # 用户连接使用验证过的对应模型。
				item,key=self.store.credentials(identity,version);model=model or item["default_model"] # 固定当前版本。
				validation=item["validations"].get(model) # 非默认模型也单独验证。
				if not validation or validation["status"]!="ready" or validation["config_version"]!=item["config_version"]: raise ConnectionError("该模型尚未通过 Agent 能力验证，请先验证","MODEL_NOT_READY",409) # 未验证不能执行。
			self.store.active[identity]=self.store.active.get(identity,0)+1 # 启动前租约防止删除竞态。
			return ManagedExecution(self,identity,item,key,model) # 保存选择的副本而非引用。

class ManagedExecution: # 一次运行持有独立 Provider 和模型配置。
	def __init__(self,manager,identity,item,key,model): # 不保存到浏览器。
		self.manager=manager;self.identity=identity;self.item=item;self.key=key;self.model=model;self.closed=False # 本次冻结配置。
	def release(self): # 拒绝并发启动或执行结束必须释放租约。
		with self.manager.store.lock: # 租约释放原子完成。
			if not self.closed: self.manager.store.active[self.identity]-=1;self.closed=True;self.key=None # 尽快释放凭据引用。
	def execute(self,request_id,description,event_sink=None): # 与现有 StreamRunner 的 Service 协议一致。
		manager=self.manager;original=manager.assembly;provider=None;assembly=None # 正确区分资源所有权。
		run_id=f"run-{uuid4()}";snapshot={"connection_id":self.identity,"connection_name":self.item["name"],"provider_id":self.item["provider_id"],"model_id":self.model,"requested_model_id":self.model,"config_version":self.item["config_version"]} # 不包含密钥或地址。
		try: # 启动失败也要释放资源和租约。
			manager.store.snapshot(run_id,snapshot) # 在 Run 创建前保存可追溯快照。
			if self.identity=="system": base_provider=original.provider # 不关闭系统共享 Provider。
			else: # 每个 Run 独立 HTTP 客户端。
				validate_endpoint(self.item["endpoint"]);provider=OpenAICompatibleProvider(self.item["endpoint"],self.key,client=manager.client_factory(),async_client_factory=None if manager.custom_client else (lambda:httpx.AsyncClient(trust_env=False,follow_redirects=False)));base_provider=provider # 受控同步 I/O超时；独立客户端不影响其他运行。
			class RecordedProvider: # 实际响应模型 ID 更新快照但不改配置选择。
				def complete(inner,request): # 沿用现有 gateway。
					try: response=base_provider.complete(request) # 请求使用冻结模型。
					except ModelProviderError as error:
						if isinstance(base_provider,MockProvider): raise # 确定性 Mock 错误不包含凭据。
						raise ModelProviderError(error.error_code,"模型调用失败，请检查连接、权限或服务状态") from None # 防止供应商原文泄露密钥。
					snapshot["model_id"]=response.model;manager.store.snapshot(run_id,snapshot) # 记录实际返回的模型标识。
					return response # 不改变工具/报告协议。
			assembly=build_agent_diagnosis_assembly(RecordedProvider(),self.item["provider_id"],original.tools,original.service_name,model=self.model,model_timeout_seconds=self.item.get("timeout_seconds",original.model_timeout_seconds),max_steps=original.max_steps,diagnosis_persistence=original.diagnosis_persistence,run_timeout_seconds=original.run_timeout_seconds,model_config=snapshot,run_id_factory=lambda:run_id) # 完整保留原有取消/预算/持久化。
			with manager.store.lock: manager.running[run_id]=assembly.diagnosis_service # 取消路由准确找到本次 Service。
			return assembly.diagnosis_service.execute(request_id,description,event_sink) # SSE 身份仍由原 Service 产生。
		finally: # 不关闭共享诊断持久化。
			with manager.store.lock: manager.running.pop(run_id,None) # 终态后由历史回查决定。
			try: # 独立 Runtime 等待工具清理。
				if assembly: assembly.runtime.close() # 不调用 assembly.close 关闭共享数据库。
			finally: # Provider 关闭不影响租约释放。
				try: # 仅关闭本次用户 Provider。
					if provider: provider.close() # 不关闭原系统服务。
				finally: self.release() # 删除不再被假占用。

def install_routes(app,manager): # 固定路径不开放任意目标代理。
	from starlette.responses import JSONResponse # 对外稳定失败响应。
	from fastapi.exceptions import RequestValidationError # 输入错误不能回显 API Key。
	@app.exception_handler(RequestValidationError)
	async def invalid_input(request,error): # 只展示字段位置，不展示 input 或原始值。
		return JSONResponse(status_code=422,content={"message":"输入无效，请检查字段长度、类型及必填项","fields":[".".join(str(part) for part in item["loc"]) for item in error.errors()]}) # 无密钥回显。
	@app.exception_handler(ConnectionError)
	async def handle_connection_error(request,error): # 不序列化内部对象。
		return JSONResponse(status_code=error.status,content={"error_code":error.code,"message":str(error)}) # 安全错误。
	@app.middleware("http")
	async def local_write_guard(request:Request,call_next): # 本机单用户凭据管理不允许跨站浏览器写入。
		if request.method not in ("GET","HEAD","OPTIONS") and request.headers.get("sec-fetch-site")=="cross-site": # 防跨站调用本机服务。
			return JSONResponse(status_code=403,content={"message":"不允许跨站写入请求"}) # 同源 Next 代理正常可用。
		return await call_next(request) # 不改 SSE 生命周期。
	@app.get("/api/v1/agent/model-services")
	def services(): return manager.services() # 供应商目录从后端声明。
	@app.get("/api/v1/agent/model-connections")
	def connections(): # 默认配置、系统连接和用户连接一次一致读取。
		with manager.store.lock: # 验证中状态与当前版本对应。
			result=manager.store.listing();result["system"]=manager.system() # 不包含密钥。
			for item in result["items"]: # 未完成请求不能显示验证通过。
				if any(identity==item["id"] and version==item["config_version"] for identity,version,model in manager.store.validating): item["status"]="verifying" # 仅当前版本。
			return result # 状态由实际操作确定。
	@app.get("/api/v1/agent/model-connections/{identity}")
	def detail(identity:str): # 详情响应与列表使用同一白名单。
		if identity=="system": return manager.system() # 系统连接无密钥。
		item,_=manager.store.credentials(identity);return manager.store.public(item,manager.store.listing()["default"]) # 不返回明文密钥。
	@app.post("/api/v1/agent/model-connections")
	def create(data:ConnectionInput): return manager.store.save(data.model_dump(exclude_none=True)) # 未验证可以保存。
	@app.patch("/api/v1/agent/model-connections/{identity}")
	def edit(identity:str,data:ConnectionInput): return manager.store.save(data.model_dump(exclude_none=True),identity) # 空密钥保留。
	@app.put("/api/v1/agent/model-connections/default")
	def default(data:DefaultInput): # 系统模型必须准确。
		if data.connection_id=="system" and data.model_id not in (None,manager.assembly.model): raise ConnectionError("系统模型不能改写") # 系统连接不可编辑。
		return {"default":manager.store.set_default(data.connection_id,data.model_id or (manager.assembly.model if data.connection_id=="system" else None),data.expected_version)} # 明确默认操作。
	@app.delete("/api/v1/agent/model-connections/{identity}")
	def delete(identity:str,data:DeleteInput): # 删除确认结果由后端最终决定。
		manager.store.delete(identity,data.expected_version,data.replacement_id);return {"deleted":True} # 成功才刷新列表。
	@app.post("/api/v1/agent/model-connections/{identity}/catalog")
	def catalog(identity:str,data:VersionInput): return manager.catalog(identity,data.expected_version) # 不随输入自动调用。
	@app.post("/api/v1/agent/model-connections/{identity}/validation")
	def validate(identity:str,data:VersionInput): return manager.validate(identity,data.expected_version,data.model_id) # 显式付费验证。
