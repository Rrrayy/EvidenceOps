from dataclasses import dataclass

from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.domain.evidence import Evidence


class AgentCollectionError(RuntimeError):
	def __init__(self,error_code:str,error_message:str)->None:
		super().__init__(error_message)
		self.error_code=error_code
		self.error_message=error_message


@dataclass(frozen=True,slots=True)
class AgentCollectionResult:
	evidences:tuple[Evidence,...]
	draft:DiagnosisDraft

	def __post_init__(self)->None:
		if not isinstance(self.evidences,tuple):
			raise TypeError("evidences必须是元组")

		for evidence in self.evidences:
			if not isinstance(evidence,Evidence):
				raise TypeError("evidences必须只包含Evidence对象")

		if not isinstance(self.draft,DiagnosisDraft):
			raise TypeError("draft必须是DiagnosisDraft对象")