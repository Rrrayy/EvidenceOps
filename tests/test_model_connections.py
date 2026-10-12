import json # 检查响应不含密钥。
from concurrent.futures import ThreadPoolExecutor # 确定性验证竞态。
from threading import Event # 控制网络响应完成顺序。
import httpx # 使用 MockTransport 不调用真实模型。
import pytest # 失败路径与临时目录。
from cryptography.fernet import Fernet # 测试独立密钥。
from fastapi.testclient import TestClient # 使用实际 API。
from evidenceops.api.agent_diagnosis import create_app # 原有诊断接口。
from evidenceops.api.model_connections import ConnectionManager # 新连接能力。
from evidenceops.infrastructure.model_connections import ConnectionStore,ConnectionError,validate_endpoint # 存储与版本边界。
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly # 独立 Run 配置。
from evidenceops.mocks.thread_pool import build_thread_pool_tool # 确定性业务工具。
from test_diagnosis_stream import TestProvider,parse_events # 复用已有报告协议测试。

def payload(**changes): # 明确测试密钥，不读用户环境。
	return {"name":"我的服务","provider_id":"custom","protocol":"chat_completions","endpoint":"https://models.example/v1","default_model":"agent-model","timeout_seconds":2,"api_key":"test-only-secret",**changes} # 不调用真实供应商。

def report(marker="evidenceops-validation-checked",identity="validation-evidence"): # 项目要求的报告格式。
	return {"root_cause":{"text":marker,"evidence_ids":[identity]},"recommendations":[{"text":"补查调用链","evidence_ids":[identity]}],"confidence":0.5,"limitations":"验证探针"} # 同真实 schema。

def response(message,status=200): # 供应商兼容响应。
	return httpx.Response(status,json={"model":"actual-agent-model","choices":[{"message":message}]}) # 记录真实返回模型标识。

def transport(request): # 响应由实际请求内容决定，而非共享索引。
	if request.method=="GET": return httpx.Response(200,json={"data":[{"id":"agent-model"},{"id":"agent-model"},{"id":"other-model"}]}) # 检查目录去重。
	body=json.loads(request.content) # 检查真实请求体。
	if any(tool.get("function",{}).get("name")=="evidenceops_probe" for tool in body.get("tools",[])): return response({"content":None,"tool_calls":[{"id":"probe-call","type":"function","function":{"name":"evidenceops_probe","arguments":"{}"}}]}) # 真实工具 ID。
	if body.get("response_format"): # 工具结果必须有关联。
		assert any(message.get("tool_call_id")=="probe-call" for message in body["messages"]) # 未关联不能通过。
		return response({"content":json.dumps(report())}) # 项目报告探针。
	return response({"content":"OK"}) # 认证与模型响应。

@pytest.fixture
def manager(tmp_path,monkeypatch): # 每项测试独立配置库。
	monkeypatch.setenv("EVIDENCEOPS_MODEL_ALLOWED_HOSTS","models.example") # 管理员明确测试主机。
	assembly=build_agent_diagnosis_assembly(TestProvider(),"test-system",(build_thread_pool_tool(),),"order-service",model="system-model",max_steps=3) # 不关闭共享数据库。
	store=ConnectionStore(tmp_path,Fernet.generate_key()) # 不创建用户凭据。
	manager=ConnectionManager(assembly,store,lambda:httpx.Client(transport=httpx.MockTransport(transport))) # 禁止真实网络。
	yield manager # 完成时释放 Runtime。
	assembly.close() # 资源生命周期。

def test_encrypted_persistence_read_and_key_replacement(manager): # 保存后重启仍可读，但 API 没有密钥。
	item=manager.store.save(payload()) # 未验证真实落盘。
	assert item["status"]=="unverified" and "secret" not in json.dumps(item) # 不回读密钥。
	assert b"test-only-secret" not in manager.store.path.read_bytes() # 文件不保存明文。
	updated=manager.store.save(payload(api_key="",endpoint=None,expected_version=1),item["id"]) # 留空保留密钥。
	assert manager.store.credentials(item["id"])[1]=="test-only-secret" # 不是掩码值。
	manager.store.save(payload(api_key="replacement-secret",expected_version=updated["config_version"]),item["id"]) # 明确替换。
	assert manager.store.credentials(item["id"])[1]=="replacement-secret" # 使用替换后的密钥。
	with pytest.raises(ConnectionError): manager.store.save(payload(api_key="******",expected_version=3),item["id"]) # 掩码拒绝。

def test_catalog_and_four_real_capability_checks(manager): # 不把目录等同于验证。
	item=manager.store.save(payload()) # 初始未就绪。
	assert len(manager.catalog(item["id"],1)["items"])==2 # 去重目录。
	result=manager.validate(item["id"],1) # 三个实际协议请求。
	assert result["status"]=="ready" and all(check["status"]=="passed" for check in result["checks"]) # 全部真实通过。
	lease=manager.choose(item["id"],"agent-model",1) # 仅已验证模型能选择。
	lease.release() # 不遗留删除占用。
	with pytest.raises(ConnectionError): manager.choose(item["id"],"other-model",1) # 目录模型不能直接执行。

def test_validation_matches_agent_without_forced_tool_choice(manager): # 支持工具但拒绝额外强制参数的兼容服务不应被误判。
	item=manager.store.save(payload());bodies=[] # 记录真正发出的验证参数。
	def compatible(request): # 模拟正常工具调用支持与 forced choice 不兼容。
		body=json.loads(request.content);bodies.append(body) # 不读取用户真实凭据。
		if "tool_choice" in body: return httpx.Response(400,json={"error":{"code":"unsupported_parameter"}}) # 旧验证会得到 partial。
		return transport(request) # 根据 tools 实际返回工具调用。
	manager.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(compatible)) # 确定性兼容端点。
	result=manager.validate(item["id"],1) # 完整工具关联和报告验证仍执行。
	assert result["status"]=="ready" and len(bodies)==3 # 没有降级跳过工具检查。
	assert all("tool_choice" not in body for body in bodies) # 与实际 Agent 参数一致。

def test_stale_validation_is_rejected(manager): # 旧请求返回不覆盖新配置。
	item=manager.store.save(payload());started=Event();release=Event() # 用事件而非时间猜测。
	def delayed(request): # 控制供应商响应。
		started.set();assert release.wait(5);return transport(request) # 延迟首个请求。
	manager.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(delayed)) # 使用同一受控接口。
	with ThreadPoolExecutor() as executor: # 验证和修改并发。
		future=executor.submit(manager.validate,item["id"],1);assert started.wait(3) # 验证已固定旧配置。
		manager.store.save(payload(default_model="new-model",api_key="",expected_version=1),item["id"]) # 改变模型使旧验证失效。
		release.set() # 返回旧结果。
		with pytest.raises(ConnectionError,match="旧结果"): future.result() # CAS 拒绝结果。
	assert manager.store.listing()["items"][0]["status"]=="stale" # 不显示 ready。

def test_default_selection_delete_lease_and_snapshot(manager): # 临时选择不改默认；运行快照不随配置改名。
	item=manager.store.save(payload());manager.validate(item["id"],1) # 准备已验证连接。
	manager.store.set_default(item["id"],"agent-model",1) # 独立设置默认。
	lease=manager.choose("system") # 临时选择系统。
	assert manager.store.listing()["default"]["connection_id"]==item["id"] # 默认没有被切换。
	lease.release();lease=manager.choose() # 新运行使用默认。
	with pytest.raises(ConnectionError,match="正在被诊断"): manager.store.delete(item["id"],1) # 使用中拒绝删除。
	manager.store.snapshot("run-history",{"connection_name":"旧名称","model_id":"agent-model"}) # 已启动历史。
	manager.store.save(payload(name="新名称",api_key="",expected_version=1),item["id"]) # 连接改名。
	assert lease.item["name"]=="我的服务" # 租约已固定旧快照。
	lease.release();manager.store.delete(item["id"],2) # 删除默认显式无替代。
	assert manager.store.listing()["default"] is None and manager.store.snapshot("run-history")["connection_name"]=="旧名称" # 历史保留。

@pytest.mark.parametrize("status,expected",[(401,"failed"),(403,"failed"),(404,"failed"),(429,"failed"),(503,"failed")])
def test_validation_http_failures_do_not_become_ready(manager,status,expected): # 错误原文可能包含密钥，不回传。
	item=manager.store.save(payload());manager.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,text="test-only-secret"))) # 故障输入。
	result=manager.validate(item["id"],1) # 真实错误分类。
	assert result["status"]==expected and "test-only-secret" not in json.dumps(result) # 不泄露供应商原文。

def test_partial_tools_and_catalog_unsupported(manager): # 部分通过、目录不支持单独处理。
	item=manager.store.save(payload()) # 初始连接。
	def no_tools(request): # 普通模型能连接但不会工具调用。
		if request.method=="GET": return httpx.Response(404) # 不支持目录。
		return response({"content":"OK"}) # 普通调用成功。
	manager.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(no_tools)) # 确定性供应商。
	assert manager.catalog(item["id"],1)["status"]=="unsupported" # 手填仍可用。
	assert manager.validate(item["id"],1)["status"]=="partial" # 不标 ready。
	with pytest.raises(ConnectionError): manager.choose(item["id"],"agent-model",1) # 拒绝诊断。

def test_api_contract_and_secret_validation_errors(manager): # 输入校验错误也不能反射密钥。
	with TestClient(create_app(manager.assembly,manager)) as client: # 实际路由。
		created=client.post("/api/v1/agent/model-connections",json=payload());assert created.status_code==200 # 创建可用。
		assert "test-only-secret" not in client.get("/api/v1/agent/model-connections").text # 读取安全。
		bad_key="secret"*1000;failure=client.post("/api/v1/agent/model-connections",json=payload(api_key=bad_key)) # 超长密钥。
		assert failure.status_code==422 and bad_key not in failure.text # Pydantic input 不回传。
		result=client.post("/api/v1/agent/diagnosis/stream",json={"description":"检查线程池","connection_id":"system","model_id":"system-model"}) # 原系统连接执行。
		events=parse_events(result.text);snapshot=events[-1]["data"]["result"]["model_config"] # 终态实际快照。
		assert snapshot["connection_id"]=="system" and snapshot["model_id"]=="system-model" # 固定配置。
		assert events[0]["data"]["model_config"]["connection_id"]=="system" # 开始事件一致。

def test_endpoint_policy_does_not_echo_credentials(manager): # 受控目标不是开放代理。
	for endpoint in ("https://user:secret@models.example/v1","https://models.example/v1?api_key=secret","https://unapproved.example/v1","file:///secret"): # 凭据/未允许主机。
		with pytest.raises(ConnectionError): validate_endpoint(endpoint) # 全部拒绝。

def test_validation_timeout_and_duplicate_requests(manager): # 超时与重复请求不重复付费。
	item=manager.store.save(payload());manager.store.validating.add((item["id"],1,"agent-model")) # 活跃验证。
	with pytest.raises(ConnectionError,match="正在验证"): manager.validate(item["id"],1) # 去重。
	manager.store.validating.clear() # 释放测试租约。
	def timeout(request): raise httpx.ReadTimeout("test-only-secret") # 原始异常含密钥。
	manager.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(timeout)) # 无真实超时等待。
	result=manager.validate(item["id"],1);assert result["error_code"]=="MODEL_TIMEOUT" and "test-only-secret" not in json.dumps(result) # 清理输出。

def test_saved_connection_executes_and_history_uses_snapshot(manager,tmp_path): # 真正通过用户连接执行 Agent，而非只测试选择列表。
	from sqlalchemy import create_engine # 隔离诊断数据库。
	from sqlalchemy.orm import sessionmaker # 复用真实持久化。
	from evidenceops.infrastructure.database.models import Base # 仅建立测试表。
	from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence # 不访问业务数据库。
	engine=create_engine(f"sqlite:///{tmp_path/'runs.db'}",connect_args={"check_same_thread":False});Base.metadata.create_all(engine) # 临时完整档案。
	manager.assembly.diagnosis_persistence=SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine) # 新 Run 共享归档事务。
	item=manager.store.save(payload());manager.validate(item["id"],1) # 真验证过的模型。
	started=Event();release=Event();used_models=[] # 在运行期间编辑配置。
	def diagnostic(request): # 真实 Chat Completions 请求经过受控客户端。
		body=json.loads(request.content);used_models.append(body["model"]) # 记录所有轮次的实际选择。
		observations=[json.loads(message["content"]) for message in body["messages"] if message["role"]=="tool"] # 工具关联数据。
		if not observations: # 等待测试改变全局配置。
			started.set();assert release.wait(5) # 不能由默认变更修改已启动 Run。
			return response({"content":None,"tool_calls":[{"id":"business-call","type":"function","function":{"name":"query_thread_pool_snapshot","arguments":'{"service_name":"order-service"}'}}]}) # 执行已有业务工具。
		return response({"content":json.dumps(report("线程池满载",observations[0]["evidence_id"]))}) # 引用真实工具结果 ID。
	manager.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(diagnostic)) # 不调用真实模型。
	with TestClient(create_app(manager.assembly,manager)) as client,ThreadPoolExecutor() as executor: # 同真实应用运行。
		future=executor.submit(client.post,"/api/v1/agent/diagnosis",json={"description":"检查线程池","connection_id":item["id"],"model_id":"agent-model","expected_version":1}) # 一次冻结配置。
		assert started.wait(3) # 运行已开始。
		manager.store.save(payload(name="新连接名",default_model="new-model",api_key="",expected_version=1),item["id"]) # 后续配置变更。
		manager.store.set_default("system","system-model") # 全局默认改变。
		release.set();result=future.result().json() # 完成原 Run。
		assert result["status"]=="succeeded" and used_models==["agent-model","agent-model"] # 两轮不变。
		snapshot=result["model_config"];assert snapshot["connection_name"]=="我的服务" and snapshot["config_version"]==1 # 原始快照。
		assert snapshot["model_id"]=="actual-agent-model" and snapshot["requested_model_id"]=="agent-model" # 实际返回与请求分别记录。
		history=client.get(f"/api/v1/agent/runs/{result['run_id']}").json() # 重读数据库。
		assert history["model_config"]==snapshot and history["report"] # 历史不使用当前配置。
		events=client.get(f"/api/v1/agent/runs/{result['run_id']}/events").json() # 持久化终态有同一快照。
		assert events["events"][-1]["data"]["result"]["model_config"]==snapshot # 重放身份与归档一致。
