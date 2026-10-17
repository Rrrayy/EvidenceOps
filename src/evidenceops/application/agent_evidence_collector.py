from evidenceops.application.agent_collection_result import AgentCollectionError,AgentCollectionResult
from evidenceops.application.agent_loop import AgentLoop,AgentLoopResult
from evidenceops.application.tool_errors import ToolCollectionError
from evidenceops.application.diagnosis_draft import DiagnosisDraft,InsufficientEvidence
from evidenceops.application.model_protocol import StructuredFinalAnswer
from evidenceops.application.tool_evidence_collector import ToolEvidenceCollector
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence
from evidenceops.application.run_events import RunEvents
from evidenceops.application.run_budget import RunBudget,RunBudgetExceeded
from evidenceops.application.run_control import RunCancelled,RunControl


class AgentEvidenceCollector:
	def __init__(self,agent_loop:AgentLoop,tool_collector:ToolEvidenceCollector)->None:
		self._agent_loop=agent_loop
		self._tool_collector=tool_collector

	def collect(self,run:DiagnosisRun,events:RunEvents|None=None,budget:RunBudget|None=None,
		control:RunControl|None=None)->AgentCollectionResult:
		options={}
		if events is not None:
			options["events"]=events
		if budget is not None:
			options["budget"]=budget
		if control is not None:
			options["control"]=control
		loop_result=self._agent_loop.run(run.description,run_id=run.run_id,**options)

		evidences=[]
		conversion_error=None
		try:
			# 只整理已有观察，不重新执行工具；报告或预算失败不能抹掉观测事实。
			for tool_result in loop_result.tool_results:
				if not tool_result.ok:
					if conversion_error is None:
						conversion_error=ToolCollectionError(tool_result.error_code or "TOOL_EXECUTION_FAILED",
							tool_result.error_message or "工具执行失败")
					continue
				try:
					if tool_result.tool_name in ("search_knowledge","query_parsed_logs"):
						if tool_result.bound_evidences is None:
							raise ToolCollectionError("EVIDENCE_COLLECTION_FAILED","知识结果没有绑定证据")
						evidences.extend(tool_result.bound_evidences)
					else:
						evidences.append(self._tool_collector.collect_result(run,tool_result))
				except ToolCollectionError as error:
					# 单项损坏不妨碍其余成功结果归档，保留首个转换错误。
					if conversion_error is None:
						conversion_error=error
			if loop_result.error_code is not None:
				raise AgentCollectionError(loop_result.error_code,loop_result.error_message or "Agent Loop执行失败")
			if control is not None:
				control.check()
			if budget is not None:
				budget.check()
			if conversion_error is not None:
				raise conversion_error
			return self._convert_result(loop_result,tuple(evidences))
		except RunCancelled as error:
			raise AgentCollectionError("RUN_CANCELLED",str(error),loop_result.execution_records,tuple(evidences)) from error
		except RunBudgetExceeded as error:
			raise AgentCollectionError("RUN_TIMEOUT",str(error),loop_result.execution_records,tuple(evidences)) from error
		except (AgentCollectionError,ToolCollectionError) as error:
			error.execution_records=loop_result.execution_records
			error.evidences=tuple(evidences)
			raise
		except Exception as error:
			raise AgentCollectionError("EVIDENCE_COLLECTION_FAILED","Agent结果转换失败",loop_result.execution_records,tuple(evidences)) from error

	def _convert_result(self,loop_result:AgentLoopResult,evidences:tuple[Evidence,...])->AgentCollectionResult:
		if not isinstance(loop_result.final_answer,StructuredFinalAnswer):
			raise AgentCollectionError("MODEL_PROTOCOL_ERROR","模型没有返回结构化最终答案")

		try:
			data=loop_result.final_answer.data
			if data.get("outcome")=="insufficient_evidence":
				insufficient=InsufficientEvidence.from_mapping(data)
				draft=None
			else:
				if "outcome" in data: raise ValueError("不支持的诊断outcome")
				draft=DiagnosisDraft.from_mapping(data)
		except Exception as error:
			raise AgentCollectionError("MODEL_PROTOCOL_ERROR",f"结构化最终答案无法转换为DiagnosisDraft：{error}") from error
		if draft is None:
			raise AgentCollectionError("EVIDENCE_INSUFFICIENT",insufficient.reason,
				details={"missing_information":list(insufficient.missing_information)})

		return AgentCollectionResult(
			evidences=evidences,
			draft=draft,
			execution_records=loop_result.execution_records,
		)
