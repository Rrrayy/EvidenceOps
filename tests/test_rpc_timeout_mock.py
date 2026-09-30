from evidenceops.application.diagnosis_service import DiagnosisService  # 调用真实 Service 编排流程
from evidenceops.domain.diagnosis_run import RunStatus  # 检查最终运行状态
from evidenceops.domain.evidence import EvidenceSource  # 检查证据来源
from evidenceops.mocks.rpc_timeout import MockRpcEvidenceCollector,MockRpcReportGenerator  # 注入固定案例


def test_rpc_timeout_mock_completes_with_three_evidence_sources()->None:  # 验证完整 Mock 故障案例
	service=DiagnosisService(MockRpcEvidenceCollector(),MockRpcReportGenerator(),lambda:"run-rpc-001")  # 注入固定案例和确定的运行 ID
	result=service.execute("req-rpc-001","排查 C++ RPC 超时")  # 从入口运行一次诊断
	assert result.run.status is RunStatus.SUCCEEDED  # 三个阶段全部通过后才成功
	assert {evidence.source for evidence in result.evidences}=={EvidenceSource.LOG,EvidenceSource.METRIC,EvidenceSource.CONFIG}  # 三类来源都已收集
	assert result.report is not None  # 成功结果包含报告
	assert len(result.report.root_cause.evidence_ids)==3  # 根因引用三条证据
	assert len(result.report.recommendations)==2  # 两条建议分别保存自己的引用