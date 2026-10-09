import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evidenceops.evaluation.__main__ import main
from evidenceops.evaluation.core import summarize_results
from evidenceops.evaluation.review import display_width,render_case,review_result,save_result,wrap_text


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

	def test_review_persists_comments_and_joint_rate(self):
		answers=iter(("invalid"," Y ","通过","n","","y","规则仍失败"))
		output=[]
		result=review_result(self.path,lambda prompt:next(answers),output.append)
		loaded=json.loads(self.path.read_text(encoding="utf-8"))
		self.assertEqual(result,loaded)
		self.assertEqual([item["semantic_review"]["status"] for item in loaded["results"]],["passed","failed","passed"])
		self.assertEqual(loaded["results"][0]["semantic_review"]["comment"],"通过")
		self.assertEqual(loaded["summary"]["rule_pass_rate"],2/3)
		self.assertEqual(loaded["summary"]["semantic_pass_rate"],2/3)
		self.assertEqual(loaded["summary"]["final_pass_rate"],1/3)
		self.assertIn("【诊断请求 / description】",output)
		self.assertIn("  诊断案例0",output)
		self.assertIn("【模型根因】",output)
		self.assertIn("  只支持相关性",output)
		self.assertTrue(any("不能断言因果" in line for line in output))
		self.assertIn("final_pass_rate: 33.33%",output)

	def test_interruption_preserves_completed_case_and_resumes(self):
		answers=iter(("y","已审核"))
		def read(prompt):
			try:
				return next(answers)
			except StopIteration:
				raise KeyboardInterrupt
		with self.assertRaises(KeyboardInterrupt):
			review_result(self.path,read,lambda value:None)
		loaded=json.loads(self.path.read_text(encoding="utf-8"))
		self.assertEqual(loaded["summary"]["semantic_review_pending"],2)
		self.assertEqual(loaded["summary"]["semantic_pass_rate"],1/3)
		answers=iter(("n","","y",""))
		result=review_result(self.path,lambda prompt:next(answers),lambda value:None)
		self.assertEqual(result["results"][0]["semantic_review"]["comment"],"已审核")
		self.assertEqual(result["summary"]["semantic_review_pending"],0)

	def test_expected_failure_without_report_is_reviewable(self):
		self.payload["results"]=self.payload["results"][:1]
		self.payload["results"][0]["response"]={"status":"failed","report":None,"error_detail":{"code":"INVALID_ARGUMENTS"}}
		save_result(self.path,self.payload)
		answers=iter(("y","错误符合预期"))
		output=[]
		result=review_result(self.path,lambda prompt:next(answers),output.append)
		self.assertEqual(result["summary"]["final_pass_rate"],1)
		self.assertTrue(any("INVALID_ARGUMENTS" in line for line in output))

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
		self.assertEqual(summary["semantic_pass_rate"],0)
		self.assertEqual(summary["final_pass_rate"],0)
		with self.assertRaises(ValueError):
			summarize_results([])

	def test_cli_dispatch_and_missing_file(self):
		with patch("evidenceops.evaluation.__main__.review_result") as review:
			self.assertEqual(main(["review",str(self.path)]),0)
			review.assert_called_once_with(self.path)
		with patch("sys.stderr"):
			self.assertEqual(main(["review",str(self.path.parent/"missing.json")]),2)

	def test_completed_review_recomputes_stale_summary_without_prompt(self):
		for item in self.payload["results"]:
			item["semantic_review"]["status"]="passed"
		save_result(self.path,self.payload)
		result=review_result(self.path,lambda prompt:self.fail("不应重复审核"),lambda value:None)
		self.assertEqual(result["summary"]["semantic_pass_rate"],1)
		self.assertEqual(result["summary"]["final_pass_rate"],2/3)

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
