from collections.abc import Protocol
from typing import Any

from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,KnowledgeChunk,KnowledgeDocument


class KnowledgeRepository(Protocol):
	def save_ingestion(self,document:KnowledgeDocument,version:DocumentVersion,chunk_set:ChunkSet,chunks:tuple[KnowledgeChunk,...])->bool: ...
	def load_chunks(self,document_id:str,version_id:str|None=None)->tuple[KnowledgeChunk,...]: ...
