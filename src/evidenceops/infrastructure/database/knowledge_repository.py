from sqlalchemy import select
from sqlalchemy.orm import Session

from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,KnowledgeChunk,KnowledgeDocument,SplitterConfig
from evidenceops.infrastructure.database.models import KnowledgeChunkRow,KnowledgeChunkSetRow,KnowledgeDocumentRow,KnowledgeVersionRow


class SqlAlchemyKnowledgeRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def save_ingestion(self,document:KnowledgeDocument,version:DocumentVersion,chunk_set:ChunkSet,chunks:tuple[KnowledgeChunk,...])->bool:
		document_row=self._session.get(KnowledgeDocumentRow,document.document_id)
		if document_row is None:
			document_row=KnowledgeDocumentRow(document_id=document.document_id,title=document.title,source_ref=document.source_ref)
			self._session.add(document_row)
		else:
			document_row.title=document.title
			document_row.source_ref=document.source_ref
		version_row=self._session.get(KnowledgeVersionRow,version.version_id)
		if version_row is not None:
			chunk_set_row=self._session.get(KnowledgeChunkSetRow,chunk_set.chunk_set_id)
			return chunk_set_row is not None
		version_row=KnowledgeVersionRow(version_id=version.version_id,document_id=version.document_id,source_ref=version.source_ref,content=version.content,content_hash=version.content_hash,status="draft")
		chunk_set_row=KnowledgeChunkSetRow(chunk_set_id=chunk_set.chunk_set_id,version_id=version.version_id,algorithm_version=chunk_set.config.algorithm_version,chunk_size=chunk_set.config.chunk_size,chunk_overlap=chunk_set.config.chunk_overlap)
		self._session.add(version_row)
		self._session.flush()
		self._session.add(chunk_set_row)
		self._session.flush()
		for chunk in chunks:
			self._session.add(KnowledgeChunkRow(chunk_id=chunk.chunk_id,chunk_set_id=chunk_set.chunk_set_id,chunk_index=chunk.chunk_index,start_offset=chunk.start_offset,end_offset=chunk.end_offset,content=chunk.content,content_hash=chunk.content_hash,heading_path=list(chunk.heading_path)))
		self._session.flush()
		return True

	def load_chunks(self,document_id:str,version_id:str|None=None)->tuple[KnowledgeChunk,...]:
		query=select(KnowledgeVersionRow).where(KnowledgeVersionRow.document_id==document_id)
		if version_id is not None: query=query.where(KnowledgeVersionRow.version_id==version_id)
		version_row=self._session.scalars(query.order_by(KnowledgeVersionRow.version_id.desc())).first()
		if version_row is None: return ()
		set_row=self._session.scalar(select(KnowledgeChunkSetRow).where(KnowledgeChunkSetRow.version_id==version_row.version_id).order_by(KnowledgeChunkSetRow.chunk_set_id.desc()))
		if set_row is None: return ()
		version=DocumentVersion(version_row.document_id,version_row.source_ref,version_row.content)
		config=SplitterConfig(set_row.algorithm_version,set_row.chunk_size,set_row.chunk_overlap)
		chunk_set=ChunkSet(set_row.version_id,config)
		rows=self._session.scalars(select(KnowledgeChunkRow).where(KnowledgeChunkRow.chunk_set_id==set_row.chunk_set_id).order_by(KnowledgeChunkRow.chunk_index)).all()
		return tuple(KnowledgeChunk(chunk_set,row.chunk_index,row.start_offset,row.end_offset,row.content,tuple(row.heading_path)) for row in rows)
