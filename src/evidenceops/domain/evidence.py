import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EvidenceSource(StrEnum):
	LOG="log"
	METRIC="metric"
	CONFIG="config"


@dataclass(frozen=True,slots=True)
class Evidence:
	evidence_id:str
	run_id:str
	source:EvidenceSource
	observed_at:datetime
	summary:str
	source_ref:str
	content_hash:str
	source_version:str|None=None

	def __post_init__(self)->None:
		# 类型标注不执行运行时检查，证据边界必须显式拒绝无效数据。
		for field_name,value in (("evidence_id",self.evidence_id),("run_id",self.run_id),("summary",self.summary),("source_ref",self.source_ref)):
			if not isinstance(value,str) or not value.strip():
				raise ValueError(f"{field_name}不能为空")
		if not isinstance(self.source,EvidenceSource):
			raise TypeError("source必须是EvidenceSource")
		if not isinstance(self.observed_at,datetime):
			raise TypeError("observed_at必须是datetime")
		# 无时区时间会在不同机器上产生歧义，不能进入证据链。
		if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
			raise ValueError("observed_at必须带时区")
		if not isinstance(self.content_hash,str) or re.fullmatch(r"[0-9a-f]{64}",self.content_hash) is None:
			raise ValueError("content_hash必须是64位小写十六进制SHA-256")
		if self.source_version is not None and (not isinstance(self.source_version,str) or not self.source_version.strip()):
			raise ValueError("source_version不能是空白文本")
