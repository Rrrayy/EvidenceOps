from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite

from evidenceops.domain.evidence import Evidence


@dataclass(frozen=True,slots=True)
class DiagnosisClaim:
	text:str
	evidence_ids:tuple[str,...]

	def __post_init__(self)->None:
		if not isinstance(self.text,str) or not self.text.strip():
			raise ValueError("判断内容不能为空")
		if not isinstance(self.evidence_ids,tuple) or not self.evidence_ids:
			raise ValueError("判断必须引用Evidence ID")
		for evidence_id in self.evidence_ids:
			if not isinstance(evidence_id,str) or not evidence_id.strip():
				raise ValueError("Evidence ID不能为空")
		if len(set(self.evidence_ids))!=len(self.evidence_ids):
			raise ValueError("Evidence ID不能重复")


@dataclass(frozen=True,slots=True)
class DiagnosisReport:
	run_id:str
	root_cause:DiagnosisClaim
	recommendations:tuple[DiagnosisClaim,...]
	confidence:float
	limitations:str

	def __post_init__(self)->None:
		if not isinstance(self.run_id,str) or not self.run_id.strip():
			raise ValueError("run_id不能为空")
		if not isinstance(self.root_cause,DiagnosisClaim):
			raise TypeError("root_cause必须是DiagnosisClaim")
		if not isinstance(self.recommendations,tuple) or not self.recommendations:
			raise ValueError("recommendations不能为空")
		for recommendation in self.recommendations:
			if not isinstance(recommendation,DiagnosisClaim):
				raise TypeError("建议必须是DiagnosisClaim")
		if isinstance(self.confidence,bool) or not isinstance(self.confidence,(int,float)):
			raise ValueError("confidence必须是数字")
		# 显式拒绝 NaN 和无穷大，防止异常数值进入置信度字段。
		if not isfinite(self.confidence) or not 0<=self.confidence<=1:
			raise ValueError("confidence必须在0到1之间")
		if not isinstance(self.limitations,str) or not self.limitations.strip():
			raise ValueError("limitations不能为空")


def validate_report_evidence(report:DiagnosisReport,evidences:Iterable[Evidence])->None:
	# 引用必须同时满足 ID 存在和 Run 归属；语义支持度另由评测检查。
	evidence_by_id:dict[str,Evidence]={}
	for evidence in evidences:
		if not isinstance(evidence,Evidence):
			raise TypeError("evidences中包含非Evidence对象")
		if evidence.evidence_id in evidence_by_id:
			raise ValueError(f"重复的Evidence ID: {evidence.evidence_id}")
		evidence_by_id[evidence.evidence_id]=evidence
	for claim in (report.root_cause,*report.recommendations):
		for evidence_id in claim.evidence_ids:
			evidence=evidence_by_id.get(evidence_id)
			if evidence is None:
				raise ValueError(f"Evidence ID不存在: {evidence_id}")
			if evidence.run_id!=report.run_id:
				raise ValueError(f"Evidence不属于本次运行: {evidence_id}")
