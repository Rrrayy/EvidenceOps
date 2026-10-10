from evidenceops.domain.evidence import Evidence


class ToolCollectionError(RuntimeError):
	def __init__(self,error_code:str,error_message:str,execution_records:tuple=(),evidences:tuple[Evidence,...]=())->None:
		super().__init__(error_message)
		self.error_code=error_code
		self.error_message=error_message
		self.execution_records=execution_records
		self.evidences=evidences


class UnknownServiceError(LookupError):
	pass
