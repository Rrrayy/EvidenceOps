"""评估检索基线的 Recall@K、Precision@K 和 MRR。"""
from dataclasses import dataclass

from evidenceops.application.knowledge_retrieval import KnowledgeMatch


@dataclass(frozen=True,slots=True)
class RetrievalCase:
	query:str
	relevant_chunk_ids:frozenset[str]


def evaluate_case(case:RetrievalCase,matches:tuple[KnowledgeMatch,...])->dict[str,float]:
	if not case.relevant_chunk_ids: raise ValueError("相关片段集合不能为空")
	returned={match.chunk.chunk_id for match in matches}
	hits=returned & case.relevant_chunk_ids
	precision=len(hits)/len(returned) if returned else 0.0
	recall=len(hits)/len(case.relevant_chunk_ids)
	reciprocal=0.0
	for match in matches:
		if match.chunk.chunk_id in case.relevant_chunk_ids:
			reciprocal=1/match.rank
			break
	return {"precision_at_k":precision,"recall_at_k":recall,"mrr":reciprocal}
