import json  # 检验转换结果能否编码为 JSON

from evidenceops.application.diagnosis_response import to_response  # 导入待测试函数
from evidenceops.application.diagnosis_service import DiagnosisService  # 运行真实编排流程
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator  # 使用已有 Mock 案例
from evidenceops.application.diagnosis_service import DiagnosisExecution

class EmptyCollector:  # 模拟正常查询但没有证据
	def collect(self,run):  # 满足 Service 所需的收集接口
		return ()  # 返回空证据集合


def test_success_response_is_json_serializable()->None:  # 验证成功结果的输出结构
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator(),lambda:"run-response-001")  # 组装已有依赖
	result=service.execute("req-response-001","排查 C++ RPC 超时")  # 执行一次诊断
	response=to_response(result)  # 转换内部对象
	json.dumps(response)  # 若仍有 datetime 或领域对象，编码会抛 TypeError
	assert response["status"]=="succeeded"  # 状态是普通字符串
	assert response["error_code"] is None  # 成功没有错误码
	assert len(response["evidences"])==3  # 三类证据都输出
	assert response["report"] is not None  # 成功输出报告
	assert len(response["report"]["root_cause"]["evidence_ids"])==3  # 根因保留三条引用


def test_failed_response_keeps_one_structure()->None:  # 验证失败也能输出同一结构
	service=DiagnosisService(EmptyCollector(),MockRpcReportGenerator(),lambda:"run-response-002")  # 模拟证据为空
	result=service.execute("req-response-002","排查 C++ RPC 超时")  # 执行失败路径
	response=to_response(result)  # 转换失败结果
	json.dumps(response)  # 失败结果也必须能编码为 JSON
	assert response["status"]=="failed"  # 输出失败状态
	assert response["error_code"]=="EVIDENCE_INSUFFICIENT"  # 保留准确错误码
	assert response["evidences"]==[]  # 空元组转换为 JSON 数组
	assert response["report"] is None  # 没有报告时对应 JSON null


def test_response_keeps_tool_error_detail()->None:
	service=DiagnosisService(EmptyCollector(),MockRpcReportGenerator(),lambda:"run-response-003")
	result=service.execute("req-response-003","排查 RPC 超时")

	result=DiagnosisExecution(
		run=result.run,
		evidences=result.evidences,
		report=None,
		error_detail={
			"code":"TOOL_TIMEOUT",
			"message":"工具执行超过时间限制",
		},
	)

	response=to_response(result)

	assert response["error_code"]=="EVIDENCE_INSUFFICIENT"
	assert response["error_detail"]=={
		"code":"TOOL_TIMEOUT",
		"message":"工具执行超过时间限制",
	}
	assert response["report"] is None