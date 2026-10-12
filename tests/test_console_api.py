import pytest # 测试前端新增的后端契约。
from fastapi.testclient import TestClient # 使用真实 FastAPI 路由，无需启动业务服务。
from evidenceops.api.agent_diagnosis import create_app # 与生产入口共享接口组装。
from test_trace_event_persistence import persistence,make_assembly # 复用隔离数据库与确定性模型。
from evidenceops.api.agent_diagnosis import AgentDiagnosisRequest


@pytest.mark.parametrize("description",[""," \n","?","？？？","...","🔥","\u200b","\u0000","a"*100001],ids=["empty","space","question","fullwidth","dots","emoji","invisible","control","too-long"])
@pytest.mark.parametrize("endpoint",["diagnosis","diagnosis/stream"])
def test_invalid_input_creates_no_run(persistence,monkeypatch,description,endpoint):
	assembly=make_assembly(persistence)
	def unexpected(*args,**kwargs):
		pytest.fail("无效输入不能进入诊断执行或调用模型")
	monkeypatch.setattr(assembly.diagnosis_service,"execute",unexpected)
	monkeypatch.setattr(assembly.provider,"complete",unexpected)
	with TestClient(create_app(assembly)) as client:
		assert client.post(f"/api/v1/agent/{endpoint}",json={"description":description}).status_code==422
		assert client.get("/api/v1/agent/runs").json()["items"]==[]


@pytest.mark.parametrize("description",["OOM","404","崩溃","RPC timeout","خطأ","error: 🔥","a"*100000],ids=["oom","code","chinese","rpc","arabic","log","limit"])
def test_short_fault_description_is_allowed(description):
	assert AgentDiagnosisRequest(description=description).description==description


def test_history_pagination_filter_and_literal_search(persistence):
	# 真实执行后回查，禁止列表触发新的模型调用。
	assembly=make_assembly(persistence)
	with TestClient(create_app(assembly)) as client:
		first=client.post("/api/v1/agent/diagnosis",json={"description":"rpc timeout 100%"}).json()
		second=client.post("/api/v1/agent/diagnosis",json={"description":"another diagnosis"}).json()
		assembly.diagnosis_service.execute=lambda *args,**kwargs:pytest.fail("历史不能执行诊断")
		page=client.get("/api/v1/agent/runs?limit=1").json()
		assert page["items"][0]["run_id"]==second["run_id"]
		assert page["has_more"] is True
		last=client.get("/api/v1/agent/runs?limit=1&offset=1").json()
		assert last["items"][0]["run_id"]==first["run_id"]
		assert last["has_more"] is False
		assert len(client.get("/api/v1/agent/runs?search=%25").json()["items"])==1
		assert client.get("/api/v1/agent/runs?status=failed").json()["items"]==[]
		assert client.get("/api/v1/agent/runs?limit=0").status_code==422
		assert client.get("/api/v1/agent/runs?status=invalid").status_code==422
		assert client.get(f"/api/v1/agent/runs/{first['run_id']}").json()["description"]=="rpc timeout 100%"


def test_capabilities_and_disabled_history():
	# 禁用持久化是明确错误，不是空列表。
	with TestClient(create_app(make_assembly(None))) as client:
		assert client.get("/api/v1/agent/capabilities").json()["persistence"] is False
		response=client.get("/api/v1/agent/runs")
		assert response.status_code==503
		assert response.json()["error_code"]=="PERSISTENCE_DISABLED"


def test_history_storage_failure_is_safe(persistence,monkeypatch):
	# 数据库读取失败提供稳定错误，不能泄露内部异常。
	with TestClient(create_app(make_assembly(persistence))) as client:
		def broken(*args,**kwargs):
			raise RuntimeError("private database credential")
		monkeypatch.setattr(persistence,"transaction",broken)
		response=client.get("/api/v1/agent/runs")
		assert response.status_code==503
		assert "private" not in response.text


def test_web_mock_can_handle_repeated_diagnoses(monkeypatch):
	# Web 页面会重复创建 Run；演示供应商不得耗尽全局响应序列。
	from evidenceops.api.agent_app import build_agent_app
	monkeypatch.setenv("EVIDENCEOPS_PERSISTENCE","memory")
	with TestClient(build_agent_app()) as client:
		first=client.post("/api/v1/agent/diagnosis",json={"description":"RPC timeout"}).json()
		second=client.post("/api/v1/agent/diagnosis",json={"description":"RPC timeout again"}).json()
		assert first["status"]==second["status"]=="succeeded"
		assert first["run_id"]!=second["run_id"]
		assert client.get("/api/v1/agent/capabilities").json()["provider_mode"]=="mock"
