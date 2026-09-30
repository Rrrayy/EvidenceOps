from fastapi.testclient import TestClient  # 在测试进程内模拟 HTTP 请求

from evidenceops.api.mock_diagnosis import create_app  # 创建可注入依赖的应用
from evidenceops.application.diagnosis_service import DiagnosisService  # 组装业务流程
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator  # 使用固定 Mock 案例


class EmptyCollector:  # 模拟查询成功但没有找到证据
	def collect(self,run):  # 满足 Service 要求的 collect 接口
		return ()  # 空结果会触发证据不足


def test_mock_api_returns_evidence_report()->None:  # 验证正常 HTTP 路径
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator(),lambda:"run-http-001")  # 固定 run_id 便于断言
	client=TestClient(create_app(service))  # 创建测试客户端
	response=client.post("/api/v1/mock/diagnosis",json={"description":"排查 C++ RPC 超时"})  # 提交 JSON 请求
	body=response.json()  # 解析返回的 JSON
	assert response.status_code==200  # 成功使用 HTTP 200
	assert body["status"]=="succeeded"  # Service 已完成诊断
	assert body["run_id"]=="run-http-001"  # 返回本次运行 ID
	assert body["request_id"].startswith("req-")  # 请求 ID 由入口生成
	assert len(body["evidences"])==3  # 固定案例包含三类证据
	assert body["report"] is not None  # 成功结果带报告


def test_mock_api_rejects_blank_description()->None:  # 验证请求校验
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator())  # 组装成功依赖
	client=TestClient(create_app(service))  # 创建测试客户端
	response=client.post("/api/v1/mock/diagnosis",json={"description":"   "})  # 提交纯空白描述
	assert response.status_code==422  # Pydantic 在调用 Service 前拒绝请求


def test_mock_api_returns_service_failure()->None:  # 验证业务失败仍有结构化响应
	service=DiagnosisService(EmptyCollector(),MockRpcReportGenerator(),lambda:"run-http-002")  # 注入空证据依赖
	client=TestClient(create_app(service))  # 创建测试客户端
	response=client.post("/api/v1/mock/diagnosis",json={"description":"排查 C++ RPC 超时"})  # 提交有效请求
	body=response.json()  # 解析失败响应
	assert response.status_code==503  # 当前 Mock 诊断未能完成
	assert body["status"]=="failed"  # Run 进入失败终态
	assert body["error_code"]=="EVIDENCE_INSUFFICIENT"  # 保留 Service 给出的具体原因
	assert body["evidences"]==[]  # 没有证据
	assert body["report"] is None  # 不返回无证据报告