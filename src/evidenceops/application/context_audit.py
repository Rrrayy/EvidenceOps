"""把每轮上下文组装结果与实际模型请求身份绑定。"""
from dataclasses import dataclass

from evidenceops.application.context_assembler import ContextAssembly


@dataclass(frozen=True,slots=True)
class ContextAudit:
	model_round:int
	model_request_id:str
	assembly:ContextAssembly
