from datetime import UTC,datetime  # 构造明确时区的观测时间
from hashlib import sha256  # 生成格式正确的内容指纹

import pytest  # 验证失败路径

from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport,validate_report_evidence  # 导入报告逻辑
from evidenceops.domain.evidence import Evidence,EvidenceSource  # 导入证据对象


def make_evidence(run_id:str)->Evidence:  # 为测试创建一条来源明确的证据
	content_hash=sha256(b"active_threads=64 limit=64").hexdigest()  # 计算测试源内容的指纹
	return Evidence("ev-001",run_id,EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限","rpc.log:120",content_hash)  # 返回证据


def make_report(evidence_id:str)->DiagnosisReport:  # 为测试创建带引用的报告
	root_cause=DiagnosisClaim("线程池耗尽可能导致 RPC 超时",(evidence_id,))  # 根因引用证据
	recommendation=DiagnosisClaim("检查线程池配置与任务积压",(evidence_id,))  # 建议引用证据
	return DiagnosisReport("run-001",root_cause,(recommendation,),0.8,"仅依据当前日志，尚未核对历史指标")  # 返回报告


def test_report_accepts_evidence_from_same_run()->None:  # 正常路径
	report=make_report("ev-001")  # 报告引用 ev-001
	evidence=make_evidence("run-001")  # 证据属于同一次运行
	validate_report_evidence(report,[evidence])  # 不抛异常即通过校验


def test_report_rejects_missing_evidence()->None:  # 虚构 ID 的失败路径
	report=make_report("ev-missing")  # 报告引用不存在的 ID
	with pytest.raises(ValueError):  # 期待引用校验失败
		validate_report_evidence(report,[make_evidence("run-001")])  # 提供的证据里没有该 ID


def test_report_rejects_evidence_from_other_run()->None:  # 跨运行引用的失败路径
	report=make_report("ev-001")  # 报告属于 run-001
	with pytest.raises(ValueError):  # 期待所属运行校验失败
		validate_report_evidence(report,[make_evidence("run-002")])  # 同名证据来自 run-002