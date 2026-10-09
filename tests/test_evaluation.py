import unittest
from contextlib import contextmanager
from dataclasses import replace

from evidenceops.domain.diagnosis_report import DiagnosisClaim
from evidenceops.evaluation.__main__ import PROJECT_ROOT,case_service,verify_fixtures
from evidenceops.evaluation.core import check_execution,load_cases,run_suite


class EvaluationTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.cases=load_cases(PROJECT_ROOT/"samples"/"evaluation"/"cases.json")
		with case_service(cls.cases[0],"mock") as service:
			cls.execution=service.execute("eval-test","评测器规则测试")

	def test_local_suite_and_case_isolation(self):
		report=run_suite(self.cases,lambda case:case_service(case,"mock"),"mock")
		self.assertEqual(len(self.cases),20)
		failures={item["case_id"]:[check["name"] for check in item["checks"] if not check["passed"]]
			for item in report["results"] if not item["rule_passed"]}
		self.assertEqual(failures,{})
		self.assertEqual(report["summary"]["rule_passed_count"],20)
		self.assertEqual(report["summary"]["semantic_review_pending"],20)
		self.assertEqual(report["summary"]["semantic_pass_rate"],0)
		self.assertEqual(len({item["response"]["run_id"] for item in report["results"]}),20)
		self.assertTrue(all(item["token_usage"] is None for item in report["results"]))

	def test_wrong_query_date_is_detected(self):
		records=tuple(replace(item,query_arguments={**item.query_arguments,"start_time":"2026-07-05T10:00:00+08:00"})
			if item.tool_name=="query_service_metrics" else item for item in self.execution.execution_records)
		checks=check_execution(self.cases[0],replace(self.execution,execution_records=records))
		self.assertFalse(next(item["passed"] for item in checks if item["name"]=="tool_parameters_1"))

	def test_unknown_report_evidence_is_detected(self):
		report=replace(self.execution.report,root_cause=DiagnosisClaim("虚构证据",("unknown",)))
		checks=check_execution(self.cases[0],replace(self.execution,report=report))
		self.assertFalse(next(item["passed"] for item in checks if item["name"]=="report_references"))

	def test_cross_run_evidence_is_detected(self):
		evidences=(replace(self.execution.evidences[0],run_id="another-run"),*self.execution.evidences[1:])
		checks=check_execution(self.cases[0],replace(self.execution,evidences=evidences))
		self.assertFalse(next(item["passed"] for item in checks if item["name"]=="evidence_ownership"))

	def test_missing_execution_records_is_detected(self):
		checks=check_execution(self.cases[0],replace(self.execution,execution_records=()))
		self.assertFalse(next(item["passed"] for item in checks if item["name"]=="records_present"))

	def test_execution_error_counts_in_denominator_and_continues(self):
		# 执行异常也必须计入分母，不能通过跳过崩溃案例抬高成绩。
		@contextmanager
		def factory(case):
			if case.case_id==self.cases[0].case_id:
				raise RuntimeError("secret must not be printed")
			with case_service(case,"mock") as service:
				yield service
		report=run_suite(self.cases,factory,"mock")
		self.assertEqual(report["summary"]["execution_error_count"],1)
		self.assertEqual(report["summary"]["rule_pass_rate"],19/20)
		self.assertEqual(report["results"][0]["execution_error"],"RuntimeError")

	def test_fixture_mismatch_is_rejected(self):
		case=replace(self.cases[0],fixture_hashes={"samples/logs/order-service.jsonl":"0"*64})
		with self.assertRaises(ValueError):
			verify_fixtures(case)

	def test_empty_suite_is_rejected(self):
		with self.assertRaises(ValueError):
			run_suite((),None,"mock")

	def test_evidence_content_mismatch_is_detected(self):
		evidences=tuple(replace(item,summary="错误的匹配数量") for item in self.execution.evidences)
		checks=check_execution(self.cases[0],replace(self.execution,evidences=evidences))
		self.assertFalse(next(item["passed"] for item in checks if item["name"]=="evidence_content_0"))

	def test_empty_metric_failure_occurs_after_successful_tool(self):
		case=next(item for item in self.cases if item.case_id=="empty-metric-window")
		with case_service(case,"mock") as service:
			result=service.execute("eval-empty-metric",case.description)
		self.assertEqual(result.run.error_code,"EVIDENCE_COLLECTION_FAILED")
		self.assertEqual(result.error_detail["code"],"NO_METRIC_SAMPLES")
		self.assertIsNone(result.report)
		self.assertTrue(all(item.status=="succeeded" for item in result.execution_records if item.kind=="tool"))
		self.assertTrue(all(item["passed"] for item in check_execution(case,result)))

	def test_mock_empty_logs_do_not_invent_timeouts(self):
		case=next(item for item in self.cases if item.case_id=="empty-log-window")
		with case_service(case,"mock") as service:
			result=service.execute("eval-empty-log",case.description)
		self.assertIn("日志匹配0条",result.report.root_cause.text)
		self.assertIn("不代表服务没有故障",result.report.root_cause.text)
		self.assertNotIn("线程池饱和同期出现",result.report.root_cause.text)

	def test_config_switch_returns_both_versions(self):
		case=next(item for item in self.cases if item.case_id=="config-switch-boundary")
		with case_service(case,"mock") as service:
			result=service.execute("eval-config-switch",case.description)
		self.assertEqual(len(result.evidences),2)
		self.assertIn("order-config-v1",result.evidences[0].summary)
		self.assertIn("order-config-v2",result.evidences[1].summary)

	def test_unrecorded_keyword_change_is_detected_by_eval_observer(self):
		case=next(item for item in self.cases if item.case_id=="empty-log-keyword")
		with case_service(case,"mock") as service:
			result=service.execute("eval-keyword",case.description)
			calls=service.observed_calls
		self.assertEqual(calls[0]["arguments"]["keywords"],["payment-service"])
		self.assertTrue(all(item["passed"] for item in check_execution(case,result,calls)))
		changed=({**calls[0],"arguments":{**calls[0]["arguments"],"keywords":["inventory-service"]}},)
		checks=check_execution(case,result,changed)
		self.assertFalse(next(item["passed"] for item in checks if item["name"]=="tool_parameters_0"))
