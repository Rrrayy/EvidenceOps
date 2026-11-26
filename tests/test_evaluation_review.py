import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from evidenceops.evaluation.__main__ import main
from evidenceops.evaluation.core import summarize_results
from evidenceops.evaluation.review import (case_review_binding,display_width,freeze_review_batch,import_reviews,
	load_reference_standards,render_case,review_result,save_result,summarize_semantic_reviews,write_review_template,wrap_text)


class EvaluationReviewTests(unittest.TestCase):
	def setUp(self):
		self.directory=tempfile.TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.path=Path(self.directory.name)/"eval_result.json"
		self.payload={"schema_version":1,"batch_id":"eval-test","mode":"mock","summary":{},"results":[
			{"case_id":f"case-{index}","input":f"诊断案例{index}","rule_passed":passed,"execution_error":None,
				"semantic_review":{"status":"pending","criteria":["不能断言因果"]},
				"response":{"report":{"root_cause":{"text":"只支持相关性"},"limitations":"缺少trace"}}}
			for index,passed in enumerate((True,True,False))
		]}
		save_result(self.path,self.payload)

	def test_unfrozen_result_cannot_use_report_level_yes_no_review(self):
		original=self.path.read_bytes()
		with self.assertRaisesRegex(ValueError,"review-freeze"):
			review_result(self.path,lambda prompt:self.fail("未冻结结果不能进入审核交互"))
		self.assertEqual(self.path.read_bytes(),original)

	def test_completed_reviewer_can_resume_without_duplicate_annotations(self):
		self.create_semantic_batch()
		answers=self.review_answers()
		first=review_result(self.path,lambda prompt:next(answers),lambda value:None,reviewer="reviewer-a")
		second=review_result(self.path,lambda prompt:self.fail("已完成的评审不应重复提问"),lambda value:None,
			reviewer="reviewer-a")
		self.assertEqual(len(first["results"][0]["semantic_review"]["reviews"]),1)
		self.assertEqual(len(second["results"][0]["semantic_review"]["reviews"]),1)

	def test_run_without_report_is_execution_only(self):
		self.create_semantic_batch()
		item=self.payload["results"][0]
		item["response"]["report"]=None
		item["semantic_review"]["workflow_status"]="execution_only"
		save_result(self.path,self.payload)
		result=review_result(self.path,lambda prompt:self.fail("无报告Run不进入Claim语义审核"),lambda value:None)
		self.assertEqual(result["semantic_quality"]["execution_only_cases"],1)
		self.assertEqual(result["semantic_quality"]["report_eligible_cases"],0)

	def test_invalid_result_is_rejected_before_input_or_write(self):
		self.payload["results"][2]["semantic_review"]["criteria"]=[]
		save_result(self.path,self.payload)
		original=self.path.read_bytes()
		with self.assertRaises(ValueError):
			review_result(self.path,lambda prompt:self.fail("不应开始交互"))
		self.assertEqual(self.path.read_bytes(),original)

	def test_atomic_replace_failure_preserves_original_and_cleans_temp(self):
		original=self.path.read_bytes()
		with patch("evidenceops.evaluation.review.os.replace",side_effect=PermissionError("文件占用")):
			with self.assertRaises(PermissionError):
				save_result(self.path,{"changed":True})
		self.assertEqual(self.path.read_bytes(),original)
		self.assertEqual(list(self.path.parent.iterdir()),[self.path])

	def test_pending_and_empty_metrics(self):
		summary=summarize_results(self.payload["results"])
		self.assertEqual(summary["semantic_review_pending"],3)
		self.assertNotIn("final_pass_rate",summary)
		self.assertEqual(summarize_semantic_reviews(self.payload["results"])["pending_cases"],3)
		with self.assertRaises(ValueError):
			summarize_results([])

	def create_semantic_batch(self):
		root_content="日志记录了数据库连接超时。"
		action_content="配置快照显示连接超时上限为1000毫秒。"
		evidence=(
			{"evidence_id":"run-semantic-log","source":"log","summary":"连接超时",
				"source_ref":"logs:1","content_hash":sha256(root_content.encode()).hexdigest(),
				"source_version":None,"content_snapshot":root_content,"source_metadata":{"event":"timeout"}},
			{"evidence_id":"run-semantic-config","source":"config","summary":"超时配置",
				"source_ref":"config:v1","content_hash":sha256(action_content.encode()).hexdigest(),
				"source_version":"config-v1","content_snapshot":action_content,"source_metadata":{"timeout_ms":1000}},
		)
		model_config={"model_id":"secret-model-name"}
		result={"case_id":"case-0","input":"为什么请求超时","rule_passed":True,"execution_error":None,
			"fixture_hashes":{"fixture":"hash"},"checks":[],"semantic_review":{"status":"pending","criteria":["判断引用"],
				"workflow_status":"pending","reviews":[],"reference_standard":{"scenario":"answerable",
					"expected_action":"answer","required_facts":[{"fact_id":"f1","text":"存在超时观察"}],
					"acceptable_conclusions":["已观察到请求超时"],"prohibited_inferences":["断言下游必然故障"]},
				"model_visibility":{"status":"known","model_request_id":"request-1","evidence_ids":["run-semantic-log"],
					"content_snapshots":{"run-semantic-log":root_content},"source":"captured_model_request"}},
			"response":{"run_id":"run-semantic","status":"succeeded","model_config":model_config,
				"evidences":list(evidence),"execution_records":[{"kind":"model","model_request_id":"request-1","status":"succeeded"}],
				"report":{"run_id":"run-semantic","root_cause":{"text":"请求超时，日志确认存在超时观察。","evidence_ids":["run-semantic-log"]},
					"recommendations":[{"text":"检查连接池超时配置。","evidence_ids":["run-semantic-config"]}]}}}
		result["model_requests"]=[{"request_id":"request-1","visible_evidence_ids":["run-semantic-log"]}]
		batch={"batch_id":"eval-semantic","source_result_sha256":"result-hash","case_file_sha256":"cases-hash",
			"reference_file_sha256":"refs-hash","prompt_template_sha256":"prompt-hash","corpus_snapshot_sha256":"corpus-hash",
			"model_config_sha256":"models-hash","model_ids":["secret-model-name"]}
		result["semantic_review"]["batch_binding"]=case_review_binding(batch,result)
		self.payload={"schema_version":1,"batch_id":"eval-semantic","mode":"real","summary":{},
			"review_batch":batch,"results":[result]}
		save_result(self.path,self.payload)
		return self.path

	@staticmethod
	def review_answers(root_judgement="supported"):
		return iter((root_judgement,"日志直接描述了连接超时。","s","日志正文记录请求超时。",
			"partially_supported","配置只给出上限，并未关联本次请求。","x","该配置提供排查背景，但不是此次超时的运行证据。",
			"covered","日志有直接超时记录。","complete","appropriate","当前证据足以确认超时现象，但不能判定下游故障。"))

	def test_claim_review_binds_evidence_visibility_and_requires_reasons(self):
		self.create_semantic_batch()
		self.payload["results"][0]["semantic_review"]["model_visibility"]["content_snapshots"]["run-semantic-log"]="日志记录了数据库"
		save_result(self.path,self.payload)
		output=[]
		answers=self.review_answers()
		result=review_result(self.path,lambda prompt:next(answers),output.append,reviewer="reviewer-a")
		review=result["results"][0]["semantic_review"]
		self.assertEqual(review["workflow_status"],"single_reviewer")
		claims=review["reviews"][0]["claims"]
		self.assertEqual(claims[0]["evidence_assessments"][0]["visibility"],"visible")
		self.assertTrue(claims[0]["evidence_assessments"][0]["model_visible_content_sha256"])
		self.assertEqual(claims[1]["evidence_assessments"][0]["visibility"],"collected_not_visible")
		self.assertTrue(any("模型实际收到：日志记录了数据库" in line for line in output))
		self.assertTrue(any("Evidence完整正文：日志记录了数据库连接超时。" in line for line in output))
		self.assertNotIn("secret-model-name","\n".join(output))
		self.assertEqual(result["semantic_quality"]["root_cause_support_rate"],1)
		self.assertEqual(result["semantic_quality"]["recommendation_evidence_support_rate"],0)

	def test_two_reviewers_detect_disagreement_then_adjudicate(self):
		self.create_semantic_batch()
		answers=self.review_answers("unsupported")
		review_result(self.path,lambda prompt:next(answers),lambda value:None,reviewer="reviewer-a")
		answers=self.review_answers("supported")
		result=review_result(self.path,lambda prompt:next(answers),lambda value:None,reviewer="reviewer-b")
		self.assertEqual(result["results"][0]["semantic_review"]["workflow_status"],"disputed")
		self.assertEqual(result["semantic_quality"]["disputed_cases"],1)
		answers=self.review_answers("supported")
		result=review_result(self.path,lambda prompt:next(answers),lambda value:None,
			reviewer="adjudicator-1",role="adjudicator")
		self.assertEqual(result["results"][0]["semantic_review"]["workflow_status"],"adjudicated")
		self.assertEqual(result["semantic_quality"]["adjudicated_cases"],1)
		self.assertEqual(result["semantic_quality"]["inter_rater_agreement"]["claim_agreement_rate"],0.5)

	def test_json_review_import_checks_run_claim_and_batch_binding(self):
		self.create_semantic_batch()
		template_path=self.path.with_name("review_template.json")
		write_review_template(self.path,template_path,"reviewer-json")
		template=json.loads(template_path.read_text(encoding="utf-8"))
		self.assertNotIn("secret-model-name",template_path.read_text(encoding="utf-8"))
		self.assertNotIn("eval-semantic",template_path.read_text(encoding="utf-8"))
		material=template["reviewer_material"][0]
		self.assertEqual(material["question"],"为什么请求超时")
		self.assertIn("日志记录了数据库连接超时",material["evidence"][0]["model_visible_content"])
		self.assertEqual(material["reference_standard"]["expected_action"],"answer")
		record=template["reviews"][0]
		record["reviewed_at"]="2026-11-26T10:00:00+08:00"
		for index,claim in enumerate(record["claims"]):
			claim["judgement"]="supported" if index==0 else "partially_supported"
			claim["reason"]="引用内容与判断关系已核对"
			for evidence in claim["evidence_assessments"]:
				evidence["relation"]="supports" if index==0 else "context_only"
				evidence["reason"]="按正文和Claim逐项判断"
		for fact in record["required_facts"]:
			fact["coverage"]="covered";fact["reason"]="日志正文支持"
		record["case_completeness"]="complete"
		record["answerability_assessment"]="appropriate"
		record["case_reason"]="案例层结论与实际证据充分性一致"
		template_path.write_text(json.dumps(template,ensure_ascii=False),encoding="utf-8")
		result=import_reviews(self.path,template_path)
		self.assertEqual(result["results"][0]["semantic_review"]["reviews"][0]["reviewer"],"reviewer-json")
		self.assertEqual(result["semantic_quality"]["single_reviewer_cases"],1)

	def test_freeze_records_source_hashes_and_no_report_runs_are_execution_only(self):
		from evidenceops.evaluation.__main__ import PROJECT_ROOT
		cases_path=self.path.with_name("cases.json")
		references_path=self.path.with_name("references.json")
		output_path=self.path.with_name("frozen.json")
		fixture_path=PROJECT_ROOT/"samples"/"logs"/"order-service.jsonl"
		fixture_hash=sha256(fixture_path.read_bytes()).hexdigest()
		cases={"schema_version":1,"cases":[{"case_id":"case-0","description":"为什么请求超时",
			"expected_status":"succeeded","expected_error_code":None,"tool_calls":[],"required_sources":[],
			"review_criteria":["判断引用"],"fixture_hashes":{"samples/logs/order-service.jsonl":fixture_hash}}]}
		references={"schema_version":1,"cases":[self.payload_standard()]}
		cases_path.write_text(json.dumps(cases,ensure_ascii=False),encoding="utf-8")
		references_path.write_text(json.dumps(references,ensure_ascii=False),encoding="utf-8")
		self.create_semantic_batch()
		self.payload["results"][0]["fixture_hashes"]=cases["cases"][0]["fixture_hashes"]
		self.payload["results"][0]["model_requests"]=[{"request_id":"request-1","visible_evidence_ids":["run-semantic-log"],
			"visible_evidence_snapshots":{"run-semantic-log":"日志记录了数据库连接超时。"}}]
		self.payload.pop("review_batch")
		self.payload["evaluation_batch"]={"prompt_template_sha256":"prompt-hash",
			"case_file":{"sha256":sha256(cases_path.read_bytes()).hexdigest()}}
		self.payload["results"][0]["semantic_review"].pop("batch_binding")
		save_result(self.path,self.payload)
		frozen=freeze_review_batch(self.path,cases_path,references_path,output_path)
		self.assertTrue(frozen["review_batch"]["comparison_ready"])
		self.assertEqual(frozen["review_batch"]["report_eligible_cases"],1)
		self.assertEqual(frozen["results"][0]["semantic_review"]["workflow_status"],"pending")
		with self.assertRaises(ValueError): freeze_review_batch(self.path,cases_path,references_path,output_path)

	def test_reference_set_has_rag_case_and_declares_missing_conflict_coverage(self):
		from evidenceops.evaluation.__main__ import PROJECT_ROOT
		standards=load_reference_standards(PROJECT_ROOT/"samples"/"evaluation"/"semantic_references.json")
		self.assertEqual(len(standards),21)
		self.assertEqual(standards["python-runtime-knowledge"]["scenario"],"RAG排障参考资料")
		payload=json.loads((PROJECT_ROOT/"samples"/"evaluation"/"semantic_references.json").read_text(encoding="utf-8"))
		self.assertEqual(payload["coverage_gaps"][0]["scenario"],"conflicting_evidence")

	def test_import_rejects_wrong_run_without_changing_frozen_batch(self):
		self.create_semantic_batch()
		template_path=self.path.with_name("wrong_run_review.json")
		template=write_review_template(self.path,template_path,"reviewer-json")
		template["reviews"][0]["run_id"]="run-other"
		template_path.write_text(json.dumps(template,ensure_ascii=False),encoding="utf-8")
		original=self.path.read_bytes()
		with self.assertRaisesRegex(ValueError,"run_id"):
			import_reviews(self.path,template_path)
		self.assertEqual(self.path.read_bytes(),original)

	@staticmethod
	def payload_standard():
		return {"case_id":"case-0","scenario":"answerable","expected_action":"answer",
			"required_facts":[{"fact_id":"f1","text":"存在超时观察"}],
			"acceptable_conclusions":["已观察到请求超时"],"prohibited_inferences":["断言下游必然故障"]}

	def test_cli_dispatch_and_missing_file(self):
		with patch("evidenceops.evaluation.__main__.review_result") as review:
			self.assertEqual(main(["review",str(self.path)]),0)
			review.assert_called_once_with(self.path)
		with patch("sys.stderr"):
			self.assertEqual(main(["review",str(self.path.parent/"missing.json")]),2)

	def test_completed_review_recomputes_stale_summary_without_prompt(self):
		self.create_semantic_batch()
		answers=self.review_answers()
		review_result(self.path,lambda prompt:next(answers),lambda value:None,reviewer="reviewer-a")
		payload=json.loads(self.path.read_text(encoding="utf-8"))
		payload["semantic_quality"]["pending_cases"]=99
		save_result(self.path,payload)
		result=review_result(self.path,lambda prompt:self.fail("不应重复审核"),lambda value:None,reviewer="reviewer-a")
		self.assertEqual(result["semantic_quality"]["pending_cases"],0)

	def test_readable_layout_wraps_chinese_and_preserves_evidence_ids(self):
		item=self.payload["results"][0]
		item["input"]="长段中文诊断请求"*12
		evidence_id="run-long-evidence-id-"*5
		item["response"]["report"]["recommendations"]=[{"text":"检查下游耗时"*8,"evidence_ids":[evidence_id]}]
		lines=render_case(item,1,20,40)
		self.assertIn("案例 01/20：case-0",lines)
		self.assertIn("【排查建议】",lines)
		self.assertTrue(any(line.startswith("  1. 检查下游") for line in lines))
		self.assertTrue(all(display_width(line)<=40 for line in lines))
		self.assertIn(evidence_id,"".join(line.strip() for line in lines))
		self.assertFalse(any('"evidence_ids"' in line for line in lines))

	def test_wrapping_preserves_paragraphs_and_combining_marks(self):
		text="中文ABC中文\n第二段e\u0301"
		lines=wrap_text(text,8)
		self.assertEqual("".join(lines),text.replace("\n",""))
		self.assertTrue(all(display_width(line)<=8 for line in lines))

	def test_wrapping_keeps_tool_names_and_timestamps_whole(self):
		text="中文前缀"*3+"query_service_metrics查询2026-10-05T10:02:00+08:00"
		lines=wrap_text(text,40)
		self.assertTrue(any("query_service_metrics" in line for line in lines))
		self.assertTrue(any("2026-10-05T10:02:00+08:00" in line for line in lines))
		self.assertEqual("".join(lines),text)

	def test_malformed_recommendations_rejected_before_review(self):
		self.payload["results"][0]["response"]["report"]["recommendations"]=[{"text":7}]
		save_result(self.path,self.payload)
		with self.assertRaises(ValueError):
			review_result(self.path,lambda prompt:self.fail("不应开始交互"))

	def test_output_option_writes_valid_utf8_without_powershell_pipe(self):
		with patch("evidenceops.evaluation.__main__.load_cases",return_value=()),patch(
			"evidenceops.evaluation.__main__.run_suite",return_value={**self.payload,"summary":{"rule_pass_rate":1}}
		),patch("builtins.print"):
			self.assertEqual(main(["--mode","mock","--output",str(self.path)]),0)
		loaded=json.loads(self.path.read_text(encoding="utf-8"))
		self.assertEqual(loaded["results"][0]["input"],"诊断案例0")
