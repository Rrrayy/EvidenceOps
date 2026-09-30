from datetime import UTC,datetime  # 给 Mock 证据固定的观测时间
from hashlib import sha256  # 从原始记录计算内容指纹

from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport  # 构造带引用的报告
from evidenceops.domain.diagnosis_run import DiagnosisRun  # 接收当前诊断运行
from evidenceops.domain.evidence import Evidence,EvidenceSource  # 构造不同来源的证据


def make_mock_evidence(run:DiagnosisRun,evidence_id:str,source:EvidenceSource,raw_content:str,summary:str,source_ref:str)->Evidence:  # 将一条固定原始记录转为证据
	content_hash=sha256(raw_content.encode("utf-8")).hexdigest()  # 对原始字节计算 SHA-256
	return Evidence(evidence_id,run.run_id,source,datetime(2026,9,30,10,0,tzinfo=UTC),summary,source_ref,content_hash,"mock-v1")  # 标明所属运行和 Mock 版本


class MockRpcEvidenceCollector:  # 提供一个固定的 RPC 超时案例
	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:  # 按 Service 要求返回证据元组
		log=make_mock_evidence(run,f"{run.run_id}-log",EvidenceSource.LOG,"RPC timeout; active_threads=64; pending_tasks=128","RPC 超时期间线程全部占用，任务出现积压","mock://rpc/log/120")  # 日志事实
		metric=make_mock_evidence(run,f"{run.run_id}-metric",EvidenceSource.METRIC,"active_threads=64; thread_limit=64; pending_tasks=128","活跃线程达到上限，待处理任务为 128","mock://rpc/metrics/1000")  # 指标事实
		config=make_mock_evidence(run,f"{run.run_id}-config",EvidenceSource.CONFIG,"thread_pool_size=64","线程池配置上限为 64","mock://rpc/config/thread_pool_size")  # 配置事实
		return (log,metric,config)  # 将三条事实交给 Service


class MockRpcReportGenerator:  # 用确定性规则生成候选报告
	def generate(self,run:DiagnosisRun,evidences:tuple[Evidence,...])->DiagnosisReport:  # 接收当前运行和实际收集的证据
		evidence_by_source={evidence.source:evidence for evidence in evidences}  # 按来源查找实际证据
		log=evidence_by_source[EvidenceSource.LOG]  # 找到 RPC 超时日志
		metric=evidence_by_source[EvidenceSource.METRIC]  # 找到线程池指标
		config=evidence_by_source[EvidenceSource.CONFIG]  # 找到线程池配置
		root_cause=DiagnosisClaim("线程池占满且任务积压，可能导致 RPC 请求超时",(log.evidence_id,metric.evidence_id,config.evidence_id))  # 根因引用三类事实
		check_tasks=DiagnosisClaim("检查占用线程的任务及队列积压原因",(metric.evidence_id,))  # 第一条建议引用指标
		check_config=DiagnosisClaim("结合负载评估线程池上限配置",(metric.evidence_id,config.evidence_id))  # 第二条建议引用指标和配置
		return DiagnosisReport(run.run_id,root_cause,(check_tasks,check_config),0.5,"仅使用固定 Mock 记录；置信度未校准，尚未核查真实调用链")  # 返回候选报告