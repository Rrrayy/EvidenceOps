from evidenceops.application.diagnosis_draft import (
	DiagnosisDraft,
	DiagnosisDraftClaim,
)
from evidenceops.domain.diagnosis_report import (
	DiagnosisClaim,
	DiagnosisReport,
	validate_report_evidence,
)
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence


class DraftReportGenerator:
	def generate(
		self,
		run:DiagnosisRun,
		evidences:tuple[Evidence,...],
		draft:DiagnosisDraft,
	)->DiagnosisReport:
		return build_diagnosis_report(run,draft,evidences)

def build_diagnosis_report(
	run:DiagnosisRun,
	draft:DiagnosisDraft,
	evidences:tuple[Evidence,...],
)->DiagnosisReport:
	root_cause=_build_claim(draft.root_cause)

	recommendations=tuple(
		_build_claim(recommendation)
		for recommendation in draft.recommendations
	)

	report=DiagnosisReport(
		run_id=run.run_id,
		root_cause=root_cause,
		recommendations=recommendations,
		confidence=draft.confidence,
		limitations=draft.limitations,
	)

	validate_report_evidence(report,evidences)

	return report


def _build_claim(draft_claim:DiagnosisDraftClaim)->DiagnosisClaim:
	return DiagnosisClaim(
		text=draft_claim.text,
		evidence_ids=draft_claim.evidence_ids,
	)