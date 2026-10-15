"""负责只读加载指定运行的完整诊断档案及实际模型配置。"""
from dataclasses import dataclass

from evidenceops.application.execution_record import ExecutionRecord
from evidenceops.application.evidence_repository import EvidenceRecord
from evidenceops.application.report_repository import ReportRepository
from evidenceops.application.run_repository import RunRecord
from evidenceops.domain.diagnosis_report import DiagnosisReport


@dataclass(frozen=True,slots=True)
class DiagnosisHistory:
	run:RunRecord
	evidences:tuple[EvidenceRecord,...]
	report:DiagnosisReport|None
	execution_records:tuple[ExecutionRecord,...]
	model_config:dict|None=None
	error_detail:dict|None=None


def load_diagnosis_history(persistence,run_id:str)->DiagnosisHistory|None:
	if not isinstance(run_id,str) or not run_id.strip():
		raise ValueError("run_id不能为空")

	# 查询历史不执行模型；数据库故障也不能伪装成“找不到 Run”。
	with persistence.transaction() as transaction:
		run=transaction.run.get(run_id)
		if run is None:
			return None
		# 失败说明已与终态原子写入事件，复用该事实，避免新增重复存储列。
		error_detail=None
		if hasattr(transaction,"trace_event"):
			sequence=transaction.trace_event.get_max_sequence(run_id)
			last=transaction.trace_event.list_by_run(run_id,max(0,sequence-1),1) if sequence else ()
			if last and last[0]["event"] in ("run_completed","run_failed","run_cancelled"):
				error_detail=last[0]["data"].get("result",{}).get("error_detail")
		return DiagnosisHistory(
			run=run,
			evidences=transaction.evidence.list_by_run(run_id),
			report=transaction.report.get(run_id),
			execution_records=transaction.execution_record.list_by_run(run_id),
			model_config=transaction.run.load_model(run_id) if hasattr(transaction.run,"load_model") else None,
			error_detail=error_detail,
		)
