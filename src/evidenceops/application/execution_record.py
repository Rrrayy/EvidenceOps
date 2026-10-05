from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True,slots=True)
class ExecutionRecord:
	kind:str
	started_at:datetime
	finished_at:datetime
	duration_ms:float
	status:str
	error_code:str|None=None
	run_id:str|None=None
	model_round:int|None=None
	model_request_id:str|None=None
	tool_name:str|None=None
	tool_call_id:str|None=None
	handler_started_at:datetime|None=None
	handler_finished_at:datetime|None=None
	query_arguments:dict[str,Any]|None=None
