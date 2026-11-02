from typing import Protocol

from evidenceops.application.context_assembler import ContextAssembly


class ContextAuditRepository(Protocol):
	def record(self,run_id:str,model_round:int,model_request_id:str,assembly:ContextAssembly)->None:
		...
