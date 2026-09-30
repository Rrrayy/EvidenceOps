from collections.abc import Callable  # 表示可调用的运行 ID 生成器
from typing import Protocol  # 定义收集器和报告生成器的接口
from dataclasses import dataclass  # 定义一次诊断的返回结果
from uuid import uuid4  # 默认生成唯一运行 ID

from evidenceops.domain.diagnosis_report import DiagnosisReport,validate_report_evidence  # 导入报告和引用校验
from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus  # 导入运行对象和状态
from evidenceops.domain.evidence import Evidence  # 导入证据对象


class EvidenceCollector(Protocol):  # 定义证据收集依赖的最小接口
	def collect(self,run:DiagnosisRun)->tuple[Evidence,...]:  # 根据运行上下文收集证据
		...  # Protocol 只描述接口，不提供实现


class ReportGenerator(Protocol):  # 定义报告生成依赖的最小接口
	def generate(self,run:DiagnosisRun,evidences:tuple[Evidence,...])->DiagnosisReport:  # 根据运行和证据生成报告
		...  # Protocol 只描述接口，不提供实现


@dataclass(frozen=True,slots=True)  # 结果对象创建后不允许普通修改
class DiagnosisExecution:  # 表示一次 Service 执行结果
	run:DiagnosisRun  # 保存本次诊断运行及最终状态
	evidences:tuple[Evidence,...]  # 保存本次收集到的证据
	report:DiagnosisReport|None  # 成功时保存报告，失败时为空


class DiagnosisService:  # 编排一次最小诊断闭环
	def __init__(self,evidence_collector:EvidenceCollector,report_generator:ReportGenerator,run_id_factory:Callable[[],str]|None=None)->None:  # 注入外部依赖
		self._evidence_collector=evidence_collector  # 保存证据收集器
		self._report_generator=report_generator  # 保存报告生成器
		self._run_id_factory=run_id_factory or (lambda:f"run-{uuid4()}")  # 默认生成唯一 ID，也允许测试注入确定 ID

	def execute(self,request_id:str,description:str)->DiagnosisExecution:  # 执行一次完整诊断
		run=DiagnosisRun(self._run_id_factory(),request_id,description)  # 创建处于 PENDING 的诊断运行
		run.transition(RunStatus.RUNNING)  # 只有进入 RUNNING 后才能执行后续步骤
		evidences:tuple[Evidence,...]=()  # 先准备空证据集合，便于失败时返回
		try:  # 捕获证据收集阶段的异常
			evidences=tuple(self._evidence_collector.collect(run))  # 执行 Mock 或真实证据收集器
			self._validate_collected_evidences(run,evidences)  # 确保证据对象属于本次运行
		except Exception as error:  # 将底层异常转换为稳定的业务错误码
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_COLLECTION_FAILED")  # 记录证据收集失败
			return DiagnosisExecution(run,evidences,None)  # 返回失败运行，不伪造报告
		if not evidences:  # 收集器正常返回，但本次诊断没有可引用的证据
			run.transition(RunStatus.FAILED,error_code="EVIDENCE_INSUFFICIENT")  # 记录证据不足
			return DiagnosisExecution(run,evidences,None)  # 停止流程，不调用报告生成器
		try:  # 单独处理报告生成阶段
			report=self._report_generator.generate(run,evidences)  # 让生成器根据本次运行和证据创建候选报告
		except Exception:  # 生成器超时或执行失败时进入此处
			run.transition(RunStatus.FAILED,error_code="REPORT_GENERATION_FAILED")  # 记录报告生成失败
			return DiagnosisExecution(run,evidences,None)  # 保留已收集证据，不返回报告

		try:  # 单独处理报告引用校验阶段
			validate_report_evidence(report,evidences)  # 检查根因和建议引用的证据是否存在、是否属于本次运行
		except Exception:  # 候选报告无法通过引用校验时进入此处
			run.transition(RunStatus.FAILED,error_code="INVALID_REPORT_EVIDENCE")  # 记录证据引用无效
			return DiagnosisExecution(run,evidences,None)  # 无效报告不能作为成功结果返回
		run.transition(RunStatus.SUCCEEDED)  # 所有校验通过后才进入成功终态
		return DiagnosisExecution(run,evidences,report)  # 返回完整成功结果

	@staticmethod  # 该校验不依赖 Service 实例状态
	def _validate_collected_evidences(run:DiagnosisRun,evidences:tuple[Evidence,...])->None:  # 校验证据集合的边界
		seen_ids:set[str]=set()  # 保存已经出现过的证据 ID
		for evidence in evidences:  # 逐条检查收集结果
			if not isinstance(evidence,Evidence):  # 拒绝错误对象
				raise TypeError("collector必须返回Evidence对象")  # 让 Service 进入失败路径
			if evidence.run_id!=run.run_id:  # 证据必须属于当前运行
				raise ValueError("Evidence不属于当前运行")  # 拒绝跨运行证据
			if evidence.evidence_id in seen_ids:  # 证据 ID 在一次运行中必须唯一
				raise ValueError("Evidence ID不能重复")  # 拒绝歧义证据
			seen_ids.add(evidence.evidence_id)  # 记录已经检查过的 ID