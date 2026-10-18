"""在模型调用前生成可审计的最终消息投影。"""
from dataclasses import dataclass
from typing import Any

from evidenceops.application.token_budget import ContextBudgetError,ContextConfig,HeuristicTokenEstimator,TokenLedger,TokenReservation


@dataclass(frozen=True,slots=True)
class EvidenceProjection:
	evidence_id:str
	content:str
	role:str="optional"
	identity:str|None=None


@dataclass(frozen=True,slots=True)
class ContextAssembly:
	messages:tuple[dict[str,Any],...]
	estimated_input_tokens:int
	reservation:TokenReservation
	visible_evidence_ids:tuple[str,...]
	deduplication_map:dict[str,str]
	omissions:tuple[dict[str,Any],...]


class ContextAssembler:
	def __init__(self,config:ContextConfig,estimator:HeuristicTokenEstimator|None=None)->None:
		self.config=config
		self.estimator=estimator or HeuristicTokenEstimator()

	def assemble(self,messages:tuple[dict[str,Any],...],tools:tuple[dict[str,Any],...],ledger:TokenLedger,evidences:tuple[EvidenceProjection,...]=(),response_format:str="text")->ContextAssembly:
		if not isinstance(messages,tuple) or not messages: raise ValueError("messages不能为空")
		if any(not isinstance(message,dict) or not isinstance(message.get("role"),str) for message in messages): raise ContextBudgetError("CONTEXT_PROTOCOL_INVALID","消息角色不完整")
		canonical=[]
		mapping={}
		omissions=[]
		seen=set()
		for evidence in evidences:
			if not evidence.evidence_id.strip() or not evidence.content.strip():
				raise ValueError("模型投影证据不能为空")
			identity=evidence.identity or evidence.evidence_id
			if identity in seen:
				mapping[evidence.evidence_id]=canonical[seen.index(identity)]
				omissions.append({"evidence_id":evidence.evidence_id,"reason":"duplicate","canonical_id":mapping[evidence.evidence_id]})
				continue
			seen.append(identity)
			canonical.append(evidence.evidence_id)
		candidate_messages=list(messages)
		for evidence in evidences:
			if evidence.evidence_id not in canonical: continue
			candidate_messages.append({"role":"tool","content":evidence.content,"evidence_id":evidence.evidence_id})
		estimated=self.estimator.estimate(tuple(candidate_messages),tools,response_format)
		payload={"messages":candidate_messages,"tools":tools,"response_format":response_format}
		reservation=ledger.reserve(estimated,payload)
		return ContextAssembly(tuple(candidate_messages),estimated,reservation,tuple(canonical),mapping,tuple(omissions))
