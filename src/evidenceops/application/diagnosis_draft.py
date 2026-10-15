from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True,slots=True)
class InsufficientEvidence:
	reason:str
	missing_information:tuple[str,...]

	@classmethod
	def from_mapping(cls,data:Mapping[str,Any])->"InsufficientEvidence":
		# 拒答是独立结果类型，不能借此混入未经引用的根因或处置结论。
		if not isinstance(data,Mapping): raise TypeError("证据不足结果必须是JSON对象")
		if set(data)!={"outcome","reason","missing_information"} or data.get("outcome")!="insufficient_evidence":
			raise ValueError("证据不足结果必须仅包含outcome、reason、missing_information")
		reason=data["reason"]
		missing=data["missing_information"]
		if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:
			raise ValueError("reason必须是1到2000字符的非空文本")
		if not isinstance(missing,list) or not 1<=len(missing)<=8:
			raise ValueError("missing_information必须包含1到8项")
		if any(not isinstance(item,str) or not item.strip() or len(item)>500 for item in missing):
			raise ValueError("缺失信息必须是1到500字符的非空文本")
		return cls(reason.strip(),tuple(item.strip() for item in missing))


@dataclass(frozen=True,slots=True)
class DiagnosisDraftClaim:
	text:str
	evidence_ids:tuple[str,...]

	@classmethod
	def from_mapping(cls,data:Mapping[str,Any])->"DiagnosisDraftClaim":
		if not isinstance(data,Mapping):
			raise TypeError("判断必须是JSON对象")

		text=data.get("text")
		evidence_ids=data.get("evidence_ids")

		if not isinstance(text,str) or not text.strip():
			raise ValueError("判断内容不能为空")

		if not isinstance(evidence_ids,(list,tuple)) or not evidence_ids:
			raise ValueError("判断必须引用Evidence ID")

		normalized_ids=tuple(evidence_ids)

		for evidence_id in normalized_ids:
			if not isinstance(evidence_id,str) or not evidence_id.strip():
				raise ValueError("Evidence ID不能为空")

		if len(set(normalized_ids))!=len(normalized_ids):
			raise ValueError("Evidence ID不能重复")

		return cls(text=text.strip(),evidence_ids=normalized_ids)


@dataclass(frozen=True,slots=True)
class DiagnosisDraft:
	root_cause:DiagnosisDraftClaim
	recommendations:tuple[DiagnosisDraftClaim,...]
	confidence:float
	limitations:str

	@classmethod
	def from_mapping(cls,data:Mapping[str,Any])->"DiagnosisDraft":
		if not isinstance(data,Mapping):
			raise TypeError("诊断草稿必须是JSON对象")

		root_cause_data=data.get("root_cause")
		recommendations_data=data.get("recommendations")
		confidence=data.get("confidence")
		limitations=data.get("limitations")

		root_cause=DiagnosisDraftClaim.from_mapping(root_cause_data)

		if not isinstance(recommendations_data,(list,tuple)):
			raise TypeError("recommendations必须是数组")

		if not recommendations_data:
			raise ValueError("recommendations不能为空")

		recommendations=tuple(DiagnosisDraftClaim.from_mapping(item) for item in recommendations_data)

		if isinstance(confidence,bool) or not isinstance(confidence,(int,float)):
			raise TypeError("confidence必须是数字")

		if not isfinite(confidence) or not 0<=confidence<=1:
			raise ValueError("confidence必须在0到1之间")

		if not isinstance(limitations,str) or not limitations.strip():
			raise ValueError("limitations不能为空")

		return cls(
			root_cause=root_cause,
			recommendations=recommendations,
			confidence=float(confidence),
			limitations=limitations.strip(),
		)
