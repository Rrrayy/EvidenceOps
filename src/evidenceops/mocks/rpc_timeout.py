from datetime import UTC,datetime
from hashlib import sha256

from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence,EvidenceSource


def make_mock_evidence(run:DiagnosisRun,evidence_id:str,source:EvidenceSource,raw_content:str,summary:str,source_ref:str)->Evidence:
	content_hash=sha256(raw_content.encode("utf-8")).hexdigest()
	return Evidence(evidence_id,run.run_id,source,datetime(2026,9,30,10,0,tzinfo=UTC),summary,source_ref,content_hash,"mock-v1")


class MockRpcEvidenceCollector:
	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:
		# 固定样本用于可重复验证，不能据此宣称已读取生产故障数据。
		log=make_mock_evidence(
			run,f"{run.run_id}-log",EvidenceSource.LOG,"RPC timeout; active_threads=64; pending_tasks=128",
			"RPC 超时期间线程全部占用，任务出现积压","mock://rpc/log/120",
		)
		metric=make_mock_evidence(
			run,f"{run.run_id}-metric",EvidenceSource.METRIC,"active_threads=64; thread_limit=64; pending_tasks=128",
			"活跃线程达到上限，待处理任务为 128","mock://rpc/metrics/1000",
		)
		config=make_mock_evidence(run,f"{run.run_id}-config",EvidenceSource.CONFIG,"thread_pool_size=64","线程池配置上限为 64","mock://rpc/config/thread_pool_size")
		return (log,metric,config)


class MockRpcReportGenerator:
	def generate(self,run:DiagnosisRun,evidences:tuple[Evidence,...])->DiagnosisReport:
		evidence_by_source={evidence.source:evidence for evidence in evidences}
		log=evidence_by_source[EvidenceSource.LOG]
		metric=evidence_by_source[EvidenceSource.METRIC]
		config=evidence_by_source[EvidenceSource.CONFIG]
		root_cause=DiagnosisClaim("线程池占满且任务积压，可能导致 RPC 请求超时",(log.evidence_id,metric.evidence_id,config.evidence_id))
		check_tasks=DiagnosisClaim("检查占用线程的任务及队列积压原因",(metric.evidence_id,))
		check_config=DiagnosisClaim("结合负载评估线程池上限配置",(metric.evidence_id,config.evidence_id))
		return DiagnosisReport(run.run_id,root_cause,(check_tasks,check_config),0.5,"仅使用固定 Mock 记录；置信度未校准，尚未核查真实调用链")
