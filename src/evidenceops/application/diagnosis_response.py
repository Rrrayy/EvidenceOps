from typing import Any

from evidenceops.application.diagnosis_service import DiagnosisExecution


def to_response(result:DiagnosisExecution)->dict[str,Any]:
	run=result.run
	evidence_items=[]

	for evidence in result.evidences:
		evidence_items.append({
			"evidence_id":evidence.evidence_id,
			"source":evidence.source.value,
			"observed_at":evidence.observed_at.isoformat(),
			"summary":evidence.summary,
			"source_ref":evidence.source_ref,
			"content_hash":evidence.content_hash,
			"source_version":evidence.source_version,
		})

	report_item=None

	if result.report is not None:
		report_item={
			"run_id":result.report.run_id,
			"root_cause":{
				"text":result.report.root_cause.text,
				"evidence_ids":list(result.report.root_cause.evidence_ids),
			},
			"recommendations":[
				{
					"text":claim.text,
					"evidence_ids":list(claim.evidence_ids),
				}
				for claim in result.report.recommendations
			],
			"confidence":result.report.confidence,
			"limitations":result.report.limitations,
		}

	return {
		"run_id":run.run_id,
		"request_id":run.request_id,
		"status":run.status.value,
		"error_code":run.error_code,
		"error_detail":result.error_detail,
		"created_at":run.created_at.isoformat(),
		"started_at":run.started_at.isoformat() if run.started_at is not None else None,
		"finished_at":run.finished_at.isoformat() if run.finished_at is not None else None,
		"evidences":evidence_items,
		"report":report_item,
	}