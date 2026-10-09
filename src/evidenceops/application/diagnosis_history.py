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


def load_diagnosis_history(persistence,run_id:str)->DiagnosisHistory|None:
	if not isinstance(run_id,str) or not run_id.strip():
		raise ValueError("run_id不能为空")

	# 查询历史不执行模型；数据库故障也不能伪装成“找不到 Run”。
	with persistence.transaction() as transaction:
		run=transaction.run.get(run_id)
		if run is None:
			return None
		return DiagnosisHistory(
			run=run,
			evidences=transaction.evidence.list_by_run(run_id),
			report=transaction.report.get(run_id),
			execution_records=transaction.execution_record.list_by_run(run_id),
		)
