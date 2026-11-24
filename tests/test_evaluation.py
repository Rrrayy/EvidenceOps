import unittest
from contextlib import contextmanager
from dataclasses import replace

from evidenceops.domain.diagnosis_report import DiagnosisClaim
from evidenceops.evaluation.__main__ import PROJECT_ROOT,case_service,verify_fixtures
from evidenceops.evaluation.core import calculate_cost,check_execution,load_cases,match_calls,match_dependencies,run_suite,summarize_usage


class EvaluationTests(unittest.TestCase):
	def test_one_to_one_calls_and_independent_order(self):
		calls=({"tool_name":"logs","arguments":{"service":"a"}},
			{"tool_name":"metrics","arguments":{"service":"a"}})
		self.assertTrue(match_calls(calls,tuple(reversed(calls))))
		self.assertFalse(match_calls(calls,calls+(calls[0],)))
		self.assertFalse(match_calls((calls[0],calls[0]),(calls[0],)))
		self.assertFalse(match_calls(calls,(calls[0],{"tool_name":"metrics","arguments":{"service":"b"}})))

	def test_matching_handles_overlapping_expected_arguments(self):
		expected=({"tool_name":"logs","arguments":{}},{"tool_name":"logs","arguments":{"service":"a"}})
		actual=({"tool_name":"logs","arguments":{"service":"a"}},{"tool_name":"logs","arguments":{"service":"b"}})
		self.assertTrue(match_calls(expected,actual))

	def test_nested_parameter_types_are_compared(self):
		expected=({"tool_name":"logs","arguments":{"options":{"values":[1]}}},)
		actual=({"tool_name":"logs","arguments":{"options":{"values":[True]}}},)
		self.assertFalse(match_calls(expected,actual))
		self.assertTrue(match_calls(expected,expected))

	def test_invalid_pricing_fails_before_running_cases(self):
		def factory(case):
			self.fail("invalid pricing must be rejected before execution")
		for pricing in ([],{}, {"model":"x","currency":"CNY","version":"1","input_per_million":"-1","output_per_million":"1"}):
			with self.assertRaises(ValueError):
				run_suite((self.cases[0],),factory,"mock",pricing)

	def test_strict_arguments_reject_extra_parameters(self):
		expected=({"tool_name":"logs","arguments":{"service":"a"},"strict_arguments":True},)
		exact=({"tool_name":"logs","arguments":{"service":"a"}},)
		extra=({"tool_name":"logs","arguments":{"service":"a","limit":10}},)
		self.assertTrue(match_calls(expected,exact))
		self.assertFalse(match_calls(expected,extra))
		self.assertTrue(match_calls(({**expected[0],"strict_arguments":False},),extra))

	def test_strict_arguments_on_existing_case_rejects_extra_parameter(self):
		case=next(item for item in self.cases if item.case_id=="empty-log-keyword")
		call={**case.tool_calls[0],"strict_arguments":True}
		case=replace(case,tool_calls=(call,))
		with case_service(case,"mock") as service:
			result=service.execute("eval-strict-arguments",case.description)
			calls=service.observed_calls
		checks={item["name"]:item["passed"] for item in check_execution(case,result,calls)}
		self.assertTrue(checks["tool_calls_one_to_one"])
		changed=({**calls[0],"arguments":{**calls[0]["arguments"],"unexpected":True}},)
		checks={item["name"]:item["passed"] for item in check_execution(case,result,changed)}
		self.assertFalse(checks["tool_calls_one_to_one"])

	def test_wrong_terminal_status_and_tool_status_are_detected(self):
		from copy import copy
		from evidenceops.domain.diagnosis_run import RunStatus
		run=copy(self.execution.run)
		run._status=RunStatus.FAILED
		checks={item["name"]:item["passed"] for item in check_execution(self.cases[0],replace(self.execution,run=run))}
		self.assertFalse(checks["status"])
		first_tool=next(item for item in self.execution.execution_records if item.kind=="tool")
		records=tuple(replace(item,status="failed",error_code="TOOL_EXECUTION_FAILED") if item is first_tool else item
			for item in self.execution.execution_records)
		checks={item["name"]:item["passed"] for item in check_execution(self.cases[0],replace(self.execution,execution_records=records))}
		self.assertFalse(checks["tool_success"])

	def test_dependent_calls_require_an_earlier_model_round(self):
		expected=({"tool_name":"config","arguments":{}},
			{"tool_name":"database","arguments":{},"depends_on":[0]})
		first={"tool_name":"config","arguments":{},"model_round":1}
		second={"tool_name":"database","arguments":{},"model_round":2}
		self.assertTrue(match_dependencies(expected,(second,first)))
		self.assertFalse(match_dependencies(expected,(first,{**second,"model_round":1})))
		self.assertFalse(match_dependencies(expected,({**first,"model_round":3},second)))
		self.assertFalse(match_dependencies(expected,(first,{**second,"model_round":None})))

	def test_mock_executes_dependent_calls_in_separate_rounds(self):
		case=self.cases[0]
		calls=list(case.tool_calls)
		calls[1]={**calls[1],"depends_on":[0]}
		case=replace(case,tool_calls=tuple(calls))
		with case_service(case,"mock") as service:
			result=service.execute("eval-dependent",case.description)
			checks={item["name"]:item["passed"] for item in check_execution(case,result,service.observed_calls)}
		self.assertTrue(checks["tool_dependencies"])
		self.assertTrue(checks["tool_calls_one_to_one"])

	def test_dependency_matching_backtracks_for_identical_calls(self):
		expected=({"tool_name":"logs","arguments":{}},
			{"tool_name":"logs","arguments":{},"depends_on":[0]})
		actual=({"tool_name":"logs","arguments":{},"model_round":2},
			{"tool_name":"logs","arguments":{},"model_round":1})
		self.assertTrue(match_dependencies(expected,actual))

	def test_dependency_check_uses_execution_rounds(self):
		case=replace(self.cases[0],tool_calls=tuple(
			{**call,"depends_on":[0]} if index==1 else call
			for index,call in enumerate(self.cases[0].tool_calls)))
		records=tuple(replace(item,model_round=2) if item.tool_name==case.tool_calls[1]["tool_name"] else item
			for item in self.execution.execution_records)
		checks={item["name"]:item["passed"] for item in check_execution(case,replace(self.execution,execution_records=records))}
		self.assertTrue(checks["tool_dependencies"])
		checks={item["name"]:item["passed"] for item in check_execution(case,self.execution)}
		self.assertFalse(checks["tool_dependencies"])

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
		self.assertTrue(all(item["token_usage"]["unknown_calls"]>0 for item in report["results"]))

	def test_usage_aggregation_distinguishes_reported_and_unknown(self):
		model=next(item for item in self.execution.execution_records if item.kind=="model")
		complete=replace(model,usage_status="complete",reported_input_tokens=10,reported_output_tokens=4,reported_total_tokens=14,estimated_input_tokens=12)
		missing=replace(model,usage_status="missing",reported_input_tokens=None,reported_output_tokens=None,reported_total_tokens=None,estimated_input_tokens=20)
		usage=summarize_usage((complete,missing))
		self.assertEqual(usage["status"],"partial")
		self.assertEqual(usage["reported_total_tokens"],14)
		self.assertEqual(usage["estimated_input_tokens"],32)
		self.assertEqual(usage["unknown_calls"],1)
		self.assertIsNone(summarize_usage((missing,))["reported_total_tokens"])

	def test_cost_uses_configured_price_and_complete_reported_usage(self):
		model=next(item for item in self.execution.execution_records if item.kind=="model")
		model=replace(model,usage_status="complete",reported_input_tokens=1000,reported_output_tokens=500,reported_total_tokens=1500)
		pricing={"model":"test-model","currency":"CNY","version":"2026-11","input_per_million":"2","output_per_million":"4"}
		self.assertEqual(calculate_cost(summarize_usage((model,)),pricing)["amount"],"0.004")
		self.assertIsNone(calculate_cost(summarize_usage((replace(model,usage_status="missing"),)),pricing))
		with self.assertRaises(ValueError):
			calculate_cost(summarize_usage((model,)),{**pricing,"input_per_million":"-1"})

	def test_cancel_timeout_and_insufficient_run_checks(self):
		from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
		for status,error in ((RunStatus.CANCELLED,None),(RunStatus.FAILED,"RUN_TIMEOUT"),
			(RunStatus.FAILED,"EVIDENCE_INSUFFICIENT")):
			run=DiagnosisRun("run-eval-terminal","request-eval-terminal","diagnosis")
			run.transition(RunStatus.RUNNING)
			run.transition(status,error)
			case=replace(self.cases[0],expected_status=status.value,expected_error_code=error,
				tool_calls=(),required_sources=(),evidence_checks=(),expected_failure_stage="run")
			model=next(item for item in self.execution.execution_records if item.kind=="model")
			result=replace(self.execution,run=run,report=None,evidences=(),error_detail=None,
				execution_records=(replace(model,run_id=run.run_id),))
			checks=check_execution(case,result,())
			self.assertTrue(all(item["passed"] for item in checks),checks)

	def test_wrong_query_date_is_detected(self):
		records=tuple(replace(item,query_arguments={**item.query_arguments,"start_time":"2026-07-05T10:00:00+08:00"})
			if item.tool_name=="query_service_metrics" else item for item in self.execution.execution_records)
		checks=check_execution(self.cases[0],replace(self.execution,execution_records=records))
		self.assertFalse(next(item["passed"] for item in checks if item["name"]=="tool_parameters_1"))

	def test_extra_call_and_duplicate_id_are_detected(self):
		tool=next(item for item in self.execution.execution_records if item.kind=="tool")
		result=replace(self.execution,execution_records=self.execution.execution_records+(tool,))
		checks={item["name"]:item["passed"] for item in check_execution(self.cases[0],result)}
		self.assertFalse(checks["tool_call_count"])
		self.assertFalse(checks["tool_call_ids_unique"])
		self.assertFalse(checks["tool_calls_one_to_one"])

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

	def test_observations_link_by_id_in_any_order(self):
		case=self.cases[0]
		with case_service(case,"mock") as service:
			result=service.execute("eval-observed-order",case.description)
			calls=service.observed_calls
		self.assertTrue(all(item["tool_call_id"] for item in calls))
		checks=check_execution(case,result,tuple(reversed(calls)))
		self.assertTrue(all(item["passed"] for item in checks))

	def test_repeated_tool_calls_keep_their_own_ids_and_arguments(self):
		original=next(item for item in self.cases if item.case_id=="empty-log-keyword")
		first=original.tool_calls[0]
		second={**first,"arguments":{**first["arguments"],"keywords":["inventory-service"]}}
		case=replace(original,tool_calls=(first,second))
		with case_service(case,"mock") as service:
			result=service.execute("eval-repeated-tools",case.description)
			calls=service.observed_calls
		self.assertEqual(len(calls),2)
		self.assertEqual(len({item["tool_call_id"] for item in calls}),2)
		self.assertEqual({tuple(item["arguments"]["keywords"]) for item in calls},
			{("payment-service",),("inventory-service",)})
		checks={item["name"]:item["passed"] for item in check_execution(case,result,tuple(reversed(calls)))}
		self.assertTrue(checks["tool_observations_linked"])
		self.assertTrue(checks["tool_calls_one_to_one"])

	def test_observation_id_and_tool_name_mismatches_fail(self):
		case=self.cases[0]
		with case_service(case,"mock") as service:
			result=service.execute("eval-observed-identity",case.description)
			calls=service.observed_calls
		variants=(
			({**calls[0],"tool_call_id":"unknown"},*calls[1:]),
			({**calls[0],"tool_call_id":calls[1]["tool_call_id"]},*calls[1:]),
			({**calls[0],"tool_name":"wrong-tool"},*calls[1:]),
			calls[1:],
		)
		for changed in variants:
			checks={item["name"]:item["passed"] for item in check_execution(case,result,changed)}
			self.assertFalse(checks["tool_observations_linked"])
			self.assertFalse(checks["tool_calls_one_to_one"])
