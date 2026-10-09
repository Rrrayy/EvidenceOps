import re
from datetime import datetime
from hashlib import sha256

from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence,EvidenceSource


class RequestLogEvidenceCollector:
	def __init__(self,log_text:str)->None:
		self._log_text=log_text

	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:
		for line_number,raw_line in enumerate(self._log_text.splitlines(),start=1):
			line=raw_line.strip()
			if "RPC timeout" not in line:
				continue

			timestamp_text,separator,_=line.partition(" ")
			if not separator:
				continue
			try:
				observed_at=datetime.fromisoformat(timestamp_text)
			except ValueError:
				continue
			if observed_at.tzinfo is None or observed_at.utcoffset() is None:
				continue

			active_match=re.search(r"\bactive_threads=(\d+)\b",line)
			limit_match=re.search(r"\bthread_limit=(\d+)\b",line)
			pending_match=re.search(r"\bpending_tasks=(\d+)\b",line)
			if active_match is None or limit_match is None or pending_match is None:
				continue

			active_threads=int(active_match.group(1))
			thread_limit=int(limit_match.group(1))
			pending_tasks=int(pending_match.group(1))
			if thread_limit==0 or active_threads<thread_limit or pending_tasks==0:
				continue

			content_hash=sha256(raw_line.encode("utf-8")).hexdigest()
			summary=f"日志记录 RPC 超时，活跃线程 {active_threads}/{thread_limit}，待处理任务 {pending_tasks}"
			evidence=Evidence(f"{run.run_id}-log-{line_number}",run.run_id,EvidenceSource.LOG,observed_at,summary,f"request.log_text:line:{line_number}",content_hash)
			return (evidence,)

		return ()


class RequestLogReportGenerator:
	def generate(self,run:DiagnosisRun,evidences:tuple[Evidence,...])->DiagnosisReport:
		log=evidences[0]
		root_cause=DiagnosisClaim("线程池满载与任务积压可能与 RPC 超时有关，根因仍待核实",(log.evidence_id,))
		recommendation=DiagnosisClaim("核对同一时段的线程池指标、任务耗时和下游 RPC 状态",(log.evidence_id,))
		return DiagnosisReport(run.run_id,root_cause,(recommendation,),0.3,"仅依据用户提交的一行日志；未独立核验来源，也未查询指标和配置")
