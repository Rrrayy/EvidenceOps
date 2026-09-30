import re  # 从一行日志中查找数字字段
from datetime import datetime  # 解析日志自身记录的事件时间
from hashlib import sha256  # 计算原始日志行的内容指纹

from evidenceops.domain.diagnosis_report import DiagnosisClaim,DiagnosisReport  # 创建报告及逐条引用
from evidenceops.domain.diagnosis_run import DiagnosisRun  # 接收当前运行上下文
from evidenceops.domain.evidence import Evidence,EvidenceSource  # 创建日志证据


class RequestLogEvidenceCollector:  # 从本次请求提交的日志中提取一条受约束的证据
	def __init__(self,log_text:str)->None:  # 每个请求创建一个独立实例
		self._log_text=log_text  # 保存本次请求的日志，不与其他请求共享

	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:  # 满足 Service 的 Collector 接口
		for line_number,raw_line in enumerate(self._log_text.splitlines(),start=1):  # 保留原文和行号
			line=raw_line.strip()  # 只用去掉首尾空白的文本识别字段
			if "RPC timeout" not in line:  # 本案例只处理明确出现 RPC timeout 的行
				continue  # 其他日志行暂不形成这类证据

			timestamp_text,separator,_=line.partition(" ")  # 取出行首的时间文本
			if not separator:  # 没有空格就没有后续日志内容
				continue  # 跳过不完整行
			try:  # 日志时间可能格式错误
				observed_at=datetime.fromisoformat(timestamp_text)  # 解析 ISO 8601 时间
			except ValueError:  # 时间无法解析
				continue  # 不编造观测时间
			if observed_at.tzinfo is None or observed_at.utcoffset() is None:  # 必须明确时区
				continue  # 避免把本地时间误认为 UTC

			active_match=re.search(r"\bactive_threads=(\d+)\b",line)  # 查活跃线程数
			limit_match=re.search(r"\bthread_limit=(\d+)\b",line)  # 查线程池上限
			pending_match=re.search(r"\bpending_tasks=(\d+)\b",line)  # 查等待任务数
			if active_match is None or limit_match is None or pending_match is None:  # 字段必须在同一行齐全
				continue  # 信息不全时不套用本案例结论

			active_threads=int(active_match.group(1))  # 将文本数字转成整数
			thread_limit=int(limit_match.group(1))  # 将线程池上限转成整数
			pending_tasks=int(pending_match.group(1))  # 将等待任务数转成整数
			if thread_limit==0 or active_threads<thread_limit or pending_tasks==0:  # 只识别满载且有积压的情况
				continue  # 不把普通 RPC 超时误报成线程池占满

			content_hash=sha256(raw_line.encode("utf-8")).hexdigest()  # 指纹对应未修改的原始日志行
			summary=f"日志记录 RPC 超时，活跃线程 {active_threads}/{thread_limit}，待处理任务 {pending_tasks}"  # 只描述观察值
			evidence=Evidence(f"{run.run_id}-log-{line_number}",run.run_id,EvidenceSource.LOG,observed_at,summary,f"request.log_text:line:{line_number}",content_hash)  # 绑定当前运行和请求内行号
			return (evidence,)  # 本阶段只取第一条符合条件的日志

		return ()  # 没有符合条件的日志时明确返回空证据


class RequestLogReportGenerator:  # 只基于这条日志形成保守候选报告
	def generate(self,run:DiagnosisRun,evidences:tuple[Evidence,...])->DiagnosisReport:  # 满足 Service 的 Generator 接口
		log=evidences[0]  # Service 已保证空证据不会进入生成阶段
		root_cause=DiagnosisClaim("线程池满载与任务积压可能与 RPC 超时有关，根因仍待核实",(log.evidence_id,))  # 候选判断引用日志证据
		recommendation=DiagnosisClaim("核对同一时段的线程池指标、任务耗时和下游 RPC 状态",(log.evidence_id,))  # 建议也明确引用依据
		return DiagnosisReport(run.run_id,root_cause,(recommendation,),0.3,"仅依据用户提交的一行日志；未独立核验来源，也未查询指标和配置")  # 明示诊断限制