from datetime import UTC,datetime
from hashlib import sha256

import pytest

from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.application.diagnosis_report_builder import build_diagnosis_report
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence,EvidenceSource


def make_run()->DiagnosisRun:
	return DiagnosisRun(
		run_id="run-001",
		request_id="req-001",
		description="分析订单服务RPC超时",
	)


def make_evidence(run_id:str,evidence_id:str="ev-001")->Evidence:
	content_hash=sha256(b"thread-pool-snapshot").hexdigest()

	return Evidence(
		evidence_id=evidence_id,
		run_id=run_id,
		source=EvidenceSource.METRIC,
		observed_at=datetime(2026,10,4,10,0,tzinfo=UTC),
		summary="线程池活跃线程达到上限",
		source_ref="tool:query_thread_pool_snapshot:service:order-service",
		content_hash=content_hash,
		source_version="mock-v1",
	)


def make_draft(evidence_id:str="ev-001")->DiagnosisDraft:
	return DiagnosisDraft.from_mapping(
		{
			"root_cause":{
				"text":"线程池耗尽导致RPC请求排队",
				"evidence_ids":[evidence_id],
			},
			"recommendations":[
				{
					"text":"扩大线程池容量并限制突发并发",
					"evidence_ids":[evidence_id],
				},
			],
			"confidence":0.91,
			"limitations":"当前只检查了线程池指标",
		}
	)


def test_build_report_from_valid_draft()->None:
	run=make_run()
	evidence=make_evidence(run.run_id)

	report=build_diagnosis_report(
		run,
		make_draft(evidence.evidence_id),
		(evidence,),
	)

	assert report.run_id==run.run_id
	assert report.root_cause.text=="线程池耗尽导致RPC请求排队"
	assert report.root_cause.evidence_ids==(evidence.evidence_id,)
	assert report.recommendations[0].evidence_ids==(evidence.evidence_id,)
	assert report.confidence==0.91


def test_builder_rejects_missing_evidence()->None:
	run=make_run()
	evidence=make_evidence(run.run_id)

	with pytest.raises(ValueError,match="Evidence ID不存在"):
		build_diagnosis_report(
			run,
			make_draft("ev-missing"),
			(evidence,),
		)


def test_builder_rejects_evidence_from_other_run()->None:
	run=make_run()
	foreign_evidence=make_evidence("run-002")

	with pytest.raises(ValueError,match="Evidence不属于本次运行"):
		build_diagnosis_report(
			run,
			make_draft(foreign_evidence.evidence_id),
			(foreign_evidence,),
		)