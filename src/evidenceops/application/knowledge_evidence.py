"""把一次检索返回的多个知识片段转换为多个可审计 Evidence。"""
from datetime import UTC,datetime
from hashlib import sha256

from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence,EvidenceSource


def matches_to_evidence(run:DiagnosisRun,tool_call_id:str,matches:tuple[KnowledgeMatch,...])->tuple[Evidence,...]:
	if not isinstance(run,DiagnosisRun) or not isinstance(tool_call_id,str) or not tool_call_id.strip():
		raise ValueError("run和tool_call_id无效")
	return tuple(Evidence(
		evidence_id=f"{run.run_id}-{tool_call_id}-{index}",run_id=run.run_id,source=EvidenceSource.KNOWLEDGE,
		observed_at=datetime.now(UTC),summary=(" / ".join(match.chunk.heading_path) or "知识片段"),
		source_ref=f"knowledge:{match.chunk.chunk_id}",content_hash=sha256(match.chunk.content.encode("utf-8")).hexdigest(),
		source_version=match.chunk.chunk_set.version_id,
	) for index,match in enumerate(matches))
