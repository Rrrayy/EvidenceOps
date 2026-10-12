from datetime import UTC,datetime

from evidenceops.application.diagnosis_history import DiagnosisHistory
from evidenceops.application.history_response import history_response
from evidenceops.domain.error_codes import ErrorCode


def recover_interrupted_runs(persistence)->int:
	count=0
	while True:
		with persistence.transaction() as transaction:
			identities=transaction.run.list_unfinished()
		if not identities:
			return count
		for run_id in identities:
			# 每个Run独立提交；启动失败后重试只处理尚未提交的Run。
			with persistence.transaction() as transaction:
				now=datetime.now(UTC)
				if not transaction.run.mark_interrupted(run_id,now,ErrorCode.RUN_INTERRUPTED.value):
					continue
				history=DiagnosisHistory(transaction.run.get(run_id),transaction.evidence.list_by_run(run_id),
					transaction.report.get(run_id),transaction.execution_record.list_by_run(run_id))
				result=history_response(history)
				# 保留已提交事实，不从tool_finished伪造Evidence或未完成执行记录。
				result["error_detail"]={"code":ErrorCode.RUN_INTERRUPTED.value,
					"message":"服务启动时发现上次进程遗留的未完成诊断；未自动重新执行"}
				transaction.trace_event.create({"event":"run_failed","run_id":run_id,
					"sequence":transaction.trace_event.get_max_sequence(run_id)+1,
					"occurred_at":now.isoformat(),"data":{"result":result}})
			count+=1
