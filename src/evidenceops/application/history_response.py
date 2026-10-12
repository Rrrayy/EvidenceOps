"""负责把持久化诊断档案转换为 API 响应。"""
def history_response(history)->dict:
	run=history.run
	return {
		"run_id":run.run_id,
		"request_id":run.request_id,
		"description":run.description,
		"status":run.status.value,
		"error_code":run.error_code,
		"model_config":getattr(history,"model_config",None),
		"created_at":run.created_at.isoformat(),
		"started_at":run.started_at.isoformat() if run.started_at else None,
		"finished_at":run.finished_at.isoformat() if run.finished_at else None,
		"evidences":[{
			"evidence_id":item.evidence_id,
			"run_id":item.run_id,
			"source":item.source,
			"observed_at":item.observed_at.isoformat(),
			"summary":item.summary,
			"source_ref":item.source_ref,
			"content_hash":item.content_hash,
			"source_version":item.source_version,
		} for item in history.evidences],
		"report":_report_response(history.report),
		"execution_records":[_execution_response(item) for item in history.execution_records],
	}


def _report_response(report):
	if report is None:
		return None

	return {
		"run_id":report.run_id,
		"root_cause":{
			"text":report.root_cause.text,
			"evidence_ids":list(report.root_cause.evidence_ids),
		},
		"recommendations":[{
			"text":claim.text,
			"evidence_ids":list(claim.evidence_ids),
		} for claim in report.recommendations],
		"confidence":report.confidence,
		"limitations":report.limitations,
	}


def _execution_response(record):
	return {
		"kind":record.kind,
		"run_id":record.run_id,
		"model_round":record.model_round,
		"model_request_id":record.model_request_id,
		"tool_name":record.tool_name,
		"tool_call_id":record.tool_call_id,
		"query_arguments":record.query_arguments,
		"started_at":record.started_at.isoformat(),
		"finished_at":record.finished_at.isoformat(),
		"duration_ms":record.duration_ms,
		"status":record.status,
		"error_code":record.error_code,
		"handler_started_at":record.handler_started_at.isoformat() if record.handler_started_at else None,
		"handler_finished_at":record.handler_finished_at.isoformat() if record.handler_finished_at else None,
	}
