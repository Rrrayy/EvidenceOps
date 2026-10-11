from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from evidenceops.application.agent_collection_result import AgentCollectionError,AgentCollectionResult
from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.application.diagnosis_persistence import DiagnosisPersistence
from evidenceops.application.execution_record import ExecutionRecord
from evidenceops.application.run_repository import RunPersistenceError
from evidenceops.application.run_events import EventSink,RunEvents
from evidenceops.application.run_budget import RunBudget,RunBudgetExceeded
from evidenceops.application.run_control import RunCancelled,RunControl,RunRegistry
from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.domain.diagnosis_report import DiagnosisReport,validate_report_evidence
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus
from evidenceops.domain.evidence import Evidence


class EvidenceCollector(Protocol):
	def collect(self,run:DiagnosisRun,events:RunEvents|None=None,budget:RunBudget|None=None,
		control:RunControl|None=None)->tuple[Evidence,...]|AgentCollectionResult:
		...


class ReportGenerator(Protocol):
	def generate(self,run:DiagnosisRun,evidences:tuple[Evidence,...],*draft:DiagnosisDraft)->DiagnosisReport:
		...


@dataclass(frozen=True,slots=True)
class DiagnosisExecution:
	run:DiagnosisRun
	evidences:tuple[Evidence,...]
	report:DiagnosisReport|None
	error_detail:dict[str,str]|None
	execution_records:tuple[ExecutionRecord,...]=()


class DiagnosisService:
	def __init__(
		self,
		evidence_collector:EvidenceCollector,
		report_generator:ReportGenerator,
		run_id_factory:Callable[[],str]|None=None,
		diagnosis_persistence:DiagnosisPersistence|None=None,
		run_timeout_seconds:float|None=None,
		cancellation_enabled:bool=False,
	)->None:
		self._evidence_collector=evidence_collector
		self._report_generator=report_generator
		self._run_id_factory=run_id_factory or (lambda:f"run-{uuid4()}")
		self._diagnosis_persistence=diagnosis_persistence
		if run_timeout_seconds is not None:
			RunBudget(run_timeout_seconds)
		self._run_timeout_seconds=run_timeout_seconds
		self._cancellation_enabled=cancellation_enabled
		self._registry=RunRegistry()

	def request_cancel(self,run_id:str)->dict|None:
		control=self._registry.get(run_id)
		return None if control is None else {"run_id":run_id,**control.request_cancel()}

	def _persist_create(self,run:DiagnosisRun)->None:
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				transaction.run.create(run)
		except Exception as error:
			raise RunPersistenceError("create",run.run_id) from error

	def _persist_update(self,run:DiagnosisRun)->None:
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				transaction.run.update(run)
		except Exception as error:
			raise RunPersistenceError("update",run.run_id) from error

	def _transition_and_persist(self,run:DiagnosisRun,next_status:RunStatus,error_code:str|None=None)->None:
		run.transition(next_status,error_code=error_code)
		self._persist_update(run)

	def _persist_success(
		self,
		run:DiagnosisRun,
		evidences:tuple[Evidence,...],
		report:DiagnosisReport,
		records:tuple[ExecutionRecord,...],
		terminal_event:dict|None=None,
	)->None:
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				for evidence in evidences:
					transaction.evidence.create(evidence)
				# 四类数据共享事务，任一步失败都不能留下半份成功档案。
				transaction.report.create(report)
				transaction.execution_record.create_many(run.run_id,records)
				transaction.run.update(run)
				if terminal_event is not None:
					transaction.trace_event.create(terminal_event)
		except Exception as error:
			raise RunPersistenceError("complete",run.run_id) from error

	def _persist_failure(self,run:DiagnosisRun,evidences:tuple[Evidence,...],records:tuple[ExecutionRecord,...],
		terminal_event:dict|None=None)->None:
		# 失败保留已交付的证据和执行记录，不保存成功报告。
		if self._diagnosis_persistence is None:
			return

		try:
			with self._diagnosis_persistence.transaction() as transaction:
				for evidence in evidences:
					transaction.evidence.create(evidence)
				transaction.execution_record.create_many(run.run_id,records)
				transaction.run.update(run)
				if terminal_event is not None:
					transaction.trace_event.create(terminal_event)
		except Exception as error:
			raise RunPersistenceError("fail",run.run_id) from error

	def execute(self,request_id:str,description:str,event_sink:EventSink|None=None)->DiagnosisExecution:
		run=DiagnosisRun(self._run_id_factory(),request_id,description)
		def persist_event(event):
			with self._diagnosis_persistence.transaction() as transaction:
				transaction.trace_event.create(event)
		events=RunEvents(run.run_id,event_sink,persist_event if self._diagnosis_persistence is not None else None) if (
			event_sink is not None or self._diagnosis_persistence is not None) else None
		budget=RunBudget(self._run_timeout_seconds) if self._run_timeout_seconds is not None else None
		try:
			result=self._execute_run(run,events) if budget is None else self._execute_run(run,events,budget)
		except Exception as error:
			if events is not None:
				events.transport_failed("PERSISTENCE_FAILED" if isinstance(error,RunPersistenceError)
					else "DIAGNOSIS_EXECUTION_FAILED")
			raise
		finally:
			self._registry.remove(run.run_id)
		return result

	def _finalize(self,result:DiagnosisExecution,events:RunEvents|None)->None:
		def commit(event=None):
			arguments=(result.run,result.evidences,result.report,result.execution_records) if (
				result.report is not None) else (result.run,result.evidences,result.execution_records)
			persist=self._persist_success if result.report is not None else self._persist_failure
			if event is not None and self._diagnosis_persistence is not None:
				persist(*arguments,terminal_event=event)
			else:
				persist(*arguments)
		if events is None:
			commit()
			return
		from evidenceops.application.diagnosis_response import to_response
		name="run_completed" if result.run.status is RunStatus.SUCCEEDED else (
			"run_cancelled" if result.run.status is RunStatus.CANCELLED else "run_failed")
		events.finish(name,{"result":to_response(result)},commit)

	def _execute_run(self,run:DiagnosisRun,events:RunEvents|None,budget:RunBudget|None=None)->DiagnosisExecution:
		# 状态更新使用短事务，模型和工具等待期间不持有数据库 Session。
		self._persist_create(run)
		self._transition_and_persist(run,RunStatus.RUNNING)
		# 外键先提交；登记与started共用事件锁，防止取消请求抢占第一条序号。
		with events.locked() if events is not None else nullcontext():
			if self._cancellation_enabled:
				self._registry.register(run.run_id,RunControl(events,budget))
			if events is not None:
				events.emit("run_started",request_id=run.request_id,status=run.status.value)
		control=self._registry.get(run.run_id)

		records:tuple[ExecutionRecord,...]=()

		def finish(*args):
			return DiagnosisExecution(*args,execution_records=records)

		evidences:tuple[Evidence,...]=()
		draft:DiagnosisDraft|None=None

		def stop(error_code,detail=None):
			if events is not None:
				events.check()
			status=control.claim_terminal(RunStatus.FAILED) if control is not None else RunStatus.FAILED
			if status is RunStatus.CANCELLED:
				detail={"code":"RUN_CANCELLED","message":"诊断已取消"}
			run.transition(status,error_code=error_code if status is RunStatus.FAILED else None)
			result=finish(run,evidences,None,detail)
			self._finalize(result,events)
			return result

		try:
			options={}
			if control is not None:
				control.check()
				options["control"]=control
			if events is not None:
				options["events"]=events
			if budget is not None:
				budget.check()
				options["budget"]=budget
			collection=self._evidence_collector.collect(run,**options)
			if events is not None:
				events.check()

			if isinstance(collection,AgentCollectionResult):
				records=collection.execution_records
				evidences=collection.evidences
				draft=collection.draft
			else:
				evidences=tuple(collection)

			self._validate_collected_evidences(run,evidences)
			if control is not None:
				control.check()
			if budget is not None:
				budget.check()

		except RunCancelled:
			return stop("RUN_CANCELLED")
		except RunBudgetExceeded:
			return stop("RUN_TIMEOUT",{"code":"RUN_TIMEOUT","message":"诊断整体执行预算已耗尽"})

		except AgentCollectionError as error:
			records=error.execution_records
			evidences=self._failure_evidences(run,error.evidences)
			return stop(error.error_code,{"code":error.error_code,"message":error.error_message})

		except ToolCollectionError as error:
			records=getattr(error,"execution_records",records)
			evidences=self._failure_evidences(run,error.evidences)
			return stop("EVIDENCE_COLLECTION_FAILED",{"code":error.error_code,"message":error.error_message})

		except Exception as error:
			records=getattr(error,"execution_records",records)
			return stop("EVIDENCE_COLLECTION_FAILED")

		if not evidences:
			return stop("EVIDENCE_INSUFFICIENT")

		if draft is not None:
			try:
				self._validate_draft_evidence(draft,evidences)
			except ValueError:
				return stop("INVALID_REPORT_EVIDENCE",{"code":"INVALID_REPORT_EVIDENCE","message":"Draft引用的证据无效"})

		try:
			if draft is None:
				report=self._report_generator.generate(run,evidences)
			else:
				report=self._report_generator.generate(run,evidences,draft)

		except Exception:
			return stop("REPORT_GENERATION_FAILED",{"code":"REPORT_GENERATION_FAILED","message":"报告生成器执行失败"})

		try:
			validate_report_evidence(report,evidences)
			if control is not None:
				control.check()
			if budget is not None:
				budget.check()

		except RunCancelled:
			return stop("RUN_CANCELLED")
		except RunBudgetExceeded:
			return stop("RUN_TIMEOUT",{"code":"RUN_TIMEOUT","message":"诊断整体执行预算已耗尽"})

		except Exception:
			return stop("INVALID_REPORT_EVIDENCE",{"code":"INVALID_REPORT_EVIDENCE","message":"报告引用的证据无效"})

		if control is not None and control.claim_terminal(RunStatus.SUCCEEDED) is RunStatus.CANCELLED:
			return stop("RUN_CANCELLED")

		run.transition(RunStatus.SUCCEEDED)
		result=finish(run,evidences,report,None)
		self._finalize(result,events)
		return result

	@staticmethod
	def _failure_evidences(run:DiagnosisRun,evidences:tuple[Evidence,...])->tuple[Evidence,...]:
		# 异常负载也需逐项校验，不能绕过归属约束；非法项不进入失败档案。
		accepted=[]
		for evidence in evidences:
			try:
				DiagnosisService._validate_collected_evidences(run,tuple(accepted)+(evidence,))
			except (TypeError,ValueError):
				continue
			accepted.append(evidence)
		return tuple(accepted)

	@staticmethod
	def _validate_collected_evidences(run:DiagnosisRun,evidences:tuple[Evidence,...])->None:
		seen_ids:set[str]=set()

		for evidence in evidences:
			if not isinstance(evidence,Evidence):
				raise TypeError("collector必须返回Evidence对象")

			if evidence.run_id!=run.run_id:
				raise ValueError("Evidence不属于当前运行")

			if evidence.evidence_id in seen_ids:
				raise ValueError("Evidence ID不能重复")

			seen_ids.add(evidence.evidence_id)

	@staticmethod
	def _validate_draft_evidence(draft:DiagnosisDraft,evidences:tuple[Evidence,...])->None:
		evidence_ids={evidence.evidence_id for evidence in evidences}
		referenced_ids=set(draft.root_cause.evidence_ids)

		for recommendation in draft.recommendations:
			referenced_ids.update(recommendation.evidence_ids)

		if not referenced_ids.issubset(evidence_ids):
			raise ValueError("Draft引用了当前运行不存在的Evidence")
