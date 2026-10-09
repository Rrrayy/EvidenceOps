from datetime import UTC,datetime
from hashlib import sha256

import pytest

from evidenceops.domain.evidence import Evidence,EvidenceSource


def test_evidence_preserves_provenance()->None:
	raw_log="active_threads=64 limit=64"
	content_hash=sha256(raw_log.encode("utf-8")).hexdigest()
	evidence=Evidence("ev-001","run-001",EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限","rpc.log:120",content_hash,"deploy-001")
	assert evidence.evidence_id=="ev-001"
	assert evidence.source_ref=="rpc.log:120"
	assert evidence.content_hash==content_hash


def test_evidence_rejects_missing_source_ref()->None:
	content_hash=sha256(b"active_threads=64").hexdigest()
	with pytest.raises(ValueError):
		Evidence("ev-002","run-001",EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限","",content_hash)
