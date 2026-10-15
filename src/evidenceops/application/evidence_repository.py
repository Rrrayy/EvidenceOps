from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from evidenceops.domain.evidence import Evidence


@dataclass(frozen=True,slots=True)
class EvidenceRecord:
	evidence_id:str
	run_id:str
	source:str
	observed_at:datetime
	summary:str
	source_ref:str
	content_hash:str
	source_version:str|None
	content_snapshot:str|None=None
	source_metadata:dict|None=None


class EvidenceRepository(Protocol):
	def create(self,evidence:Evidence)->None:
		...

	def get(self,evidence_id:str)->EvidenceRecord|None:
		...

	def list_by_run(self,run_id:str)->tuple[EvidenceRecord,...]:
		...


class EvidencePersistence(Protocol):
	def transaction(self)->AbstractContextManager[EvidenceRepository]:
		...
