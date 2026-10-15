"""把一次检索返回的多个知识片段转换为多个可审计 Evidence。"""
from datetime import UTC,datetime
from hashlib import sha256

from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.domain.diagnosis_run import DiagnosisRun
from evidenceops.domain.evidence import Evidence,EvidenceSource


def matches_to_evidence(run:DiagnosisRun|str,tool_call_id:str,matches:tuple[KnowledgeMatch,...])->tuple[Evidence,...]:
	run_id=run.run_id if isinstance(run,DiagnosisRun) else run
	if not isinstance(run_id,str) or not run_id.strip() or not isinstance(tool_call_id,str) or not tool_call_id.strip():
		raise ValueError("run和tool_call_id无效")
	return tuple(Evidence(
		evidence_id=f"{run_id}-{tool_call_id}-{index}",run_id=run_id,source=EvidenceSource.KNOWLEDGE,
		observed_at=datetime.now(UTC),summary=(" / ".join(match.chunk.heading_path) or "知识片段"),
		source_ref=f"knowledge:{match.chunk.chunk_id}",content_hash=sha256(match.chunk.content.encode("utf-8")).hexdigest(),
		source_version=match.chunk.chunk_set.version_id,
		content_snapshot=match.chunk.content,
		source_metadata={"document_id":match.document_id,"source_ref":match.source_ref,
			"chunk_id":match.chunk.chunk_id,"chunk_set_id":match.chunk.chunk_set.chunk_set_id,
			"embedding_set_id":match.embedding_set_id,"config_fingerprint":match.config_fingerprint,
			"start_offset":match.chunk.start_offset,"end_offset":match.chunk.end_offset,
			"heading_path":list(match.chunk.heading_path),"score":match.score,"rank":match.rank,
			"retrieval_method":match.retrieval_method,
			**({"retrieval_details":match.retrieval_details} if match.retrieval_details is not None else {})},
	) for index,match in enumerate(matches))
