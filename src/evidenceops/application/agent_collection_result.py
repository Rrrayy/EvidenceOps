from dataclasses import dataclass

from evidenceops.application.diagnosis_draft import DiagnosisDraft
from evidenceops.domain.evidence import Evidence
from evidenceops.application.execution_record import ExecutionRecord


class AgentCollectionError(RuntimeError):
	def __init__(self,error_code:str,error_message:str,execution_records:tuple[ExecutionRecord,...]=())->None:
		super().__init__(error_message)
		self.error_code=error_code
		self.error_message=error_message
		self.execution_records=execution_records


@dataclass(frozen=True,slots=True)
class AgentCollectionResult:
	evidences:tuple[Evidence,...]
	draft:DiagnosisDraft
	execution_records:tuple[ExecutionRecord,...]=()

	def __post_init__(self)->None:
		if not isinstance(self.evidences,tuple):
			raise TypeError("evidences必须是元组")

		for evidence in self.evidences:
			if not isinstance(evidence,Evidence):
				raise TypeError("evidences必须只包含Evidence对象")

		if not isinstance(self.draft,DiagnosisDraft):
			raise TypeError("draft必须是DiagnosisDraft对象")
