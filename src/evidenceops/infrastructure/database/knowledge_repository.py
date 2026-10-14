from sqlalchemy import select
from sqlalchemy.orm import Session

from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,KnowledgeChunk,KnowledgeDocument,SplitterConfig
from evidenceops.infrastructure.database.models import KnowledgeChunkRow,KnowledgeChunkSetRow,KnowledgeDocumentRow,KnowledgeVersionRow


class SqlAlchemyKnowledgeRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def save_ingestion(self,document:KnowledgeDocument,version:DocumentVersion,chunk_set:ChunkSet,chunks:tuple[KnowledgeChunk,...])->bool:
		if version.document_id!=document.document_id or chunk_set.version_id!=version.version_id:
			raise ValueError("文档、版本和ChunkSet之间的归属不一致")
		if not chunks or any(chunk.chunk_set.chunk_set_id!=chunk_set.chunk_set_id for chunk in chunks):
			raise ValueError("chunks必须属于给定ChunkSet")
		document_row=self._session.get(KnowledgeDocumentRow,document.document_id)
		if document_row is None:
			document_row=KnowledgeDocumentRow(document_id=document.document_id,title=document.title,source_ref=document.source_ref)
			self._session.add(document_row)
		else:
			document_row.title=document.title
			document_row.source_ref=document.source_ref
		version_row=self._session.get(KnowledgeVersionRow,version.version_id)
		if version_row is None:
			version_row=KnowledgeVersionRow(version_id=version.version_id,document_id=version.document_id,source_ref=version.source_ref,content=version.content,content_hash=version.content_hash,status="draft")
			self._session.add(version_row)
			self._session.flush()
		chunk_set_row=self._session.get(KnowledgeChunkSetRow,chunk_set.chunk_set_id)
		if chunk_set_row is not None:
			return True
		chunk_set_row=KnowledgeChunkSetRow(chunk_set_id=chunk_set.chunk_set_id,version_id=version.version_id,algorithm_version=chunk_set.config.algorithm_version,chunk_size=chunk_set.config.chunk_size,chunk_overlap=chunk_set.config.chunk_overlap)
		self._session.add(chunk_set_row)
		self._session.flush()
		for chunk in chunks:
			self._session.add(KnowledgeChunkRow(chunk_id=chunk.chunk_id,chunk_set_id=chunk_set.chunk_set_id,chunk_index=chunk.chunk_index,start_offset=chunk.start_offset,end_offset=chunk.end_offset,content=chunk.content,content_hash=chunk.content_hash,heading_path=list(chunk.heading_path)))
		self._session.flush()
		return True

	def load_chunks(self,document_id:str,chunk_set_id:str,chunk_ids:frozenset[str]|None=None,limit:int|None=None)->tuple[KnowledgeChunk,...]:
		if not isinstance(chunk_set_id,str) or not chunk_set_id.strip():
			raise ValueError("chunk_set_id必须是非空文本")
		set_row=self._session.get(KnowledgeChunkSetRow,chunk_set_id)
		if set_row is None: return ()
		version_row=self._session.get(KnowledgeVersionRow,set_row.version_id)
		if version_row is None or version_row.document_id!=document_id: return ()
		version=DocumentVersion(version_row.document_id,version_row.source_ref,version_row.content)
		config=SplitterConfig(set_row.algorithm_version,set_row.chunk_size,set_row.chunk_overlap)
		chunk_set=ChunkSet(set_row.version_id,config)
		statement=select(KnowledgeChunkRow).where(KnowledgeChunkRow.chunk_set_id==set_row.chunk_set_id)
		if chunk_ids is not None: statement=statement.where(KnowledgeChunkRow.chunk_id.in_(chunk_ids))
		statement=statement.order_by(KnowledgeChunkRow.chunk_index)
		if limit is not None: statement=statement.limit(limit)
		rows=self._session.scalars(statement).all()
		return tuple(KnowledgeChunk(chunk_set,row.chunk_index,row.start_offset,row.end_offset,row.content,tuple(row.heading_path)) for row in rows)
