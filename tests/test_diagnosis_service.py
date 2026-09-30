from datetime import UTC,datetime  # 构造带时区的证据时间
from hashlib import sha256  # 生成合法的 SHA-256 指纹

from evidenceops.application.diagnosis_service import DiagnosisService  # 导入待测试的 Service
from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport  # 导入报告对象
from evidenceops.domain.evidence import Evidence,EvidenceSource  # 导入证据对象


def make_evidence(run_id:str,evidence_id:str="ev-001")->Evidence:  # 创建测试证据
	raw_content=f"{evidence_id}:active_threads=64 limit=64"  # 生成确定的原始内容
	content_hash=sha256(raw_content.encode("utf-8")).hexdigest()  # 计算内容指纹
	return Evidence(evidence_id,run_id,EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限",f"rpc.log:{evidence_id}",content_hash)  # 返回合法证据


class SuccessfulCollector:  # 模拟成功的证据收集器
	def collect(self,run):  # 按接口提供收集方法
		return (make_evidence(run.run_id),)  # 返回属于当前运行的证据


class FailingCollector:  # 模拟失败的证据收集器
	def collect(self,run):  # 按接口提供收集方法
		raise TimeoutError("mock collector timeout")  # 模拟连接器超时


class SuccessfulReportGenerator:  # 模拟成功的报告生成器
	def generate(self,run,evidences):  # 按接口提供报告生成方法
		evidence_id=evidences[0].evidence_id  # 读取真实证据 ID
		root_cause=DiagnosisClaim("线程池耗尽可能导致 RPC 超时",(evidence_id,))  # 创建引用真实证据的根因
		recommendation=DiagnosisClaim("检查线程池配置与任务积压",(evidence_id,))  # 创建引用真实证据的建议
		return DiagnosisReport(run.run_id,root_cause,(recommendation,),0.8,"当前仅使用 Mock 日志证据")  # 返回合法报告


class InvalidReportGenerator:  # 模拟生成错误引用的报告
	def generate(self,run,evidences):  # 按接口提供报告生成方法
		root_cause=DiagnosisClaim("线程池耗尽可能导致 RPC 超时",("ev-fake",))  # 故意引用不存在的 ID
		recommendation=DiagnosisClaim("检查线程池配置与任务积压",("ev-fake",))  # 故意引用不存在的 ID
		return DiagnosisReport(run.run_id,root_cause,(recommendation,),0.8,"Mock 报告引用了不存在的证据")  # 返回结构合法但引用无效的报告

class FailingReportGenerator:  # 模拟报告生成器发生故障
	def generate(self,run,evidences):  # 方法名称和参数必须符合 Service 调用的接口
		raise TimeoutError("mock report generation timeout")  # 模拟生成阶段超时

class EmptyCollector:  # 模拟查询成功但没有查到任何证据
	def collect(self,run):  # 保持与证据收集接口相同的方法
		return ()  # 空元组表示本次没有证据

def test_service_completes_successful_diagnosis()->None:  # 验证完整成功路径
	service=DiagnosisService(SuccessfulCollector(),SuccessfulReportGenerator(),lambda:"run-001")  # 注入两个成功 Mock 和确定的运行 ID
	result=service.execute("req-001","分析 RPC 超时")  # 执行一次诊断
	assert result.run.status.value=="succeeded"  # 确认运行成功
	assert result.run.error_code is None  # 成功运行不应有错误码
	assert len(result.evidences)==1  # 确认收集到一条证据
	assert result.evidences[0].run_id=="run-001"  # 确认证据属于当前运行
	assert result.report is not None  # 成功结果必须有报告
	assert result.report.run_id=="run-001"  # 确认报告属于当前运行


def test_service_fails_when_evidence_collection_fails()->None:  # 验证证据收集失败路径
	service=DiagnosisService(FailingCollector(),SuccessfulReportGenerator(),lambda:"run-002")  # 注入会超时的收集器
	result=service.execute("req-002","分析 RPC 超时")  # 执行一次诊断
	assert result.run.status.value=="failed"  # 确认运行进入失败状态
	assert result.run.error_code=="EVIDENCE_COLLECTION_FAILED"  # 确认错误码稳定
	assert result.report is None  # 失败时不能返回报告
	assert result.evidences==()  # 收集失败时没有证据


def test_service_fails_when_report_references_unknown_evidence()->None:  # 验证报告引用失败路径
	service=DiagnosisService(SuccessfulCollector(),InvalidReportGenerator(),lambda:"run-003")  # 注入错误报告生成器
	result=service.execute("req-003","分析 RPC 超时")  # 执行一次诊断
	assert result.run.status.value=="failed"  # 确认运行进入失败状态
	assert result.run.error_code=="INVALID_REPORT_EVIDENCE"  # 确认错误码稳定
	assert result.report is None  # 无效报告不能被返回为成功结果
	assert len(result.evidences)==1  # 报告失败前证据已经成功收集


def test_service_fails_when_report_generation_times_out()->None:  # 验证生成失败有独立错误码
	service=DiagnosisService(SuccessfulCollector(),FailingReportGenerator(),lambda:"run-004")  # 证据收集成功，报告生成失败
	result=service.execute("req-004","分析 RPC 超时")  # 运行完整 Service 流程
	assert result.run.status.value=="failed"  # Run 必须进入失败终态
	assert result.run.error_code=="REPORT_GENERATION_FAILED"  # 错误码应指出失败发生在生成阶段
	assert len(result.evidences)==1  # 报告失败前已经收集的证据仍然保留
	assert result.report is None  # 失败时没有可交付报告

def test_service_fails_before_generating_report_when_evidence_is_empty()->None:  # 验证空证据路径
	service=DiagnosisService(EmptyCollector(),SuccessfulReportGenerator(),lambda:"run-005")  # 注入返回空证据的收集器
	result=service.execute("req-005","分析 RPC 超时")  # 执行诊断
	assert result.run.status.value=="failed"  # 诊断应以失败状态结束
	assert result.run.error_code=="EVIDENCE_INSUFFICIENT"  # 错误应归因于证据不足
	assert result.evidences==()  # 确认没有收集到证据
	assert result.report is None  # 没有证据时不能交付报告