"""编排知识文件加载、版本构造和切分；不写数据库、不发布版本。"""
from dataclasses import dataclass
from pathlib import Path

from evidenceops.application.knowledge_splitter import KnowledgeSplitter
from evidenceops.connectors.local_document import DocumentInput,LocalDocumentLoader
from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,KnowledgeChunk,KnowledgeDocument,SplitterConfig


@dataclass(frozen=True,slots=True)
class IngestionResult:
	document:KnowledgeDocument
	version:DocumentVersion
	chunk_set:ChunkSet
	chunks:tuple[KnowledgeChunk,...]
	is_new_version:bool


class DocumentIngestionService:
	"""同一对象内以稳定 version_id 去重；数据库阶段会替换这个内存索引。"""
	def __init__(self,loader:LocalDocumentLoader,splitter:KnowledgeSplitter|None=None)->None:
		if not isinstance(loader,LocalDocumentLoader):
			raise TypeError("loader必须是LocalDocumentLoader")
		self._loader=loader
		self._splitter=splitter or KnowledgeSplitter()
		self._versions:dict[tuple[str,str],IngestionResult]={}

	def ingest(self,document:KnowledgeDocument,relative_path:str,config:SplitterConfig|None=None)->IngestionResult:
		if not isinstance(document,KnowledgeDocument):
			raise TypeError("document必须是KnowledgeDocument")
		if not isinstance(relative_path,str) or not relative_path.strip():
			raise ValueError("relative_path必须是非空文本")
		if config is None:
			config=SplitterConfig()
		if not isinstance(config,SplitterConfig):
			raise TypeError("config必须是SplitterConfig")
		loaded=self._loader.load(relative_path,purpose="knowledge")
		version=DocumentVersion(document.document_id,loaded.source_ref,loaded.content)
		chunk_set=ChunkSet(version.version_id,config)
		cache_key=(version.version_id,chunk_set.chunk_set_id)
		cached=self._versions.get(cache_key)
		if cached is not None:
			return IngestionResult(cached.document,cached.version,cached.chunk_set,cached.chunks,False)
		chunks=self._splitter.split(version,chunk_set)
		result=IngestionResult(document,version,chunk_set,chunks,True)
		self._versions[cache_key]=result
		return result

	def get_cached(self,version_id:str,chunk_set_id:str)->IngestionResult|None:
		if not isinstance(version_id,str) or not version_id.strip():
			raise ValueError("version_id必须是非空文本")
		if not isinstance(chunk_set_id,str) or not chunk_set_id.strip():
			raise ValueError("chunk_set_id必须是非空文本")
		return self._versions.get((version_id,chunk_set_id))
