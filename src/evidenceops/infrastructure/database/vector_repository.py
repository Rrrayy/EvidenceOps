from dataclasses import asdict
from typing import NamedTuple
from sqlalchemy import func,select

from evidenceops.domain.knowledge_vectors import EncodingConfig,validate_vectors
from evidenceops.infrastructure.database.models import KnowledgeChunkRow,KnowledgeDocumentRow,KnowledgeEmbeddingSetRow,KnowledgePublicationRow,KnowledgeVectorRow,KnowledgeChunkSetRow,KnowledgeVersionRow
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository


class PublicationConflict(RuntimeError):
	pass


class PublicationPointer(NamedTuple):
	chunk_set_id:str
	embedding_set_id:str|None


class VectorRepository:
	def __init__(self,session)->None:
		self.session=session

	def create(self,set_id:str,chunk_set_id:str,config:EncodingConfig)->None:
		self.session.add(KnowledgeEmbeddingSetRow(embedding_set_id=set_id,chunk_set_id=chunk_set_id,config=asdict(config),config_fingerprint=config.fingerprint,status="pending"))
		self.session.flush()

	def transition(self,set_id:str,expected:str,status:str,error_code:str|None=None)->None:
		row=self.session.scalar(select(KnowledgeEmbeddingSetRow).where(KnowledgeEmbeddingSetRow.embedding_set_id==set_id).with_for_update())
		if row is None or row.status!=expected: raise ValueError("构建状态冲突")
		if (expected,status) not in (("pending","building"),("building","ready"),("building","failed")): raise ValueError("非法构建状态转换")
		row.status=status
		row.error_code=error_code

	def complete(self,set_id:str,chunks,vectors)->None:
		row=self.session.scalar(select(KnowledgeEmbeddingSetRow).where(KnowledgeEmbeddingSetRow.embedding_set_id==set_id).with_for_update())
		if row is None or row.status!="building": raise ValueError("集合不是building")
		config=EncodingConfig(**row.config)
		validated=validate_vectors(vectors,len(chunks),config.dimensions)
		chunk_set=self.session.get(KnowledgeChunkSetRow,row.chunk_set_id)
		version=self.session.get(KnowledgeVersionRow,chunk_set.version_id)
		expected=SqlAlchemyKnowledgeRepository(self.session).load_chunks(version.document_id,row.chunk_set_id)
		if tuple(chunk.chunk_id for chunk in chunks)!=tuple(chunk.chunk_id for chunk in expected): raise ValueError("向量必须完整覆盖指定ChunkSet")
		for chunk,vector in zip(chunks,validated):
			self.session.add(KnowledgeVectorRow(embedding_set_id=set_id,chunk_id=chunk.chunk_id,vector=list(vector)))
		self.session.flush()
		self.transition(set_id,"building","ready")

	def active(self,document_id:str)->str|None:
		pointer=self.active_publication(document_id)
		return pointer.embedding_set_id if pointer else None

	def active_publication(self,document_id:str)->PublicationPointer|None:
		row=self.session.get(KnowledgePublicationRow,document_id)
		return PublicationPointer(row.chunk_set_id,row.embedding_set_id) if row else None

	def publish(self,document_id:str,chunk_set_id:str,embedding_set_id:str|None,expected_active:PublicationPointer|None)->None:
		# 锁逻辑文档行并比较完整指针，首次发布和同ChunkSet更换Embedding都可串行化。
		document=self.session.scalar(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.document_id==document_id).with_for_update())
		if document is None: raise ValueError("文档不存在")
		row=self.session.get(KnowledgePublicationRow,document_id,populate_existing=True)
		current=PublicationPointer(row.chunk_set_id,row.embedding_set_id) if row else None
		if current!=expected_active: raise PublicationConflict("发布指针已变化，请重新验收后发布")
		chunk_set=self.session.get(KnowledgeChunkSetRow,chunk_set_id)
		if chunk_set is None: raise ValueError("ChunkSet不存在")
		version=self.session.get(KnowledgeVersionRow,chunk_set.version_id)
		if version is None or version.document_id!=document_id: raise ValueError("集合不属于文档")
		chunk_count=self.session.scalar(select(func.count()).select_from(KnowledgeChunkRow).where(KnowledgeChunkRow.chunk_set_id==chunk_set_id))
		if not chunk_count: raise ValueError("空ChunkSet不能发布")
		if embedding_set_id is not None:
			encoding=self.session.get(KnowledgeEmbeddingSetRow,embedding_set_id)
			if encoding is None or encoding.status!="ready": raise ValueError("仅ready向量集合可发布")
			if encoding.chunk_set_id!=chunk_set_id: raise ValueError("EmbeddingSet与ChunkSet不匹配")
			vector_count=self.session.scalar(select(func.count()).select_from(KnowledgeVectorRow).where(KnowledgeVectorRow.embedding_set_id==embedding_set_id))
			matched_count=self.session.scalar(select(func.count()).select_from(KnowledgeVectorRow).join(KnowledgeChunkRow,KnowledgeChunkRow.chunk_id==KnowledgeVectorRow.chunk_id)
				.where(KnowledgeVectorRow.embedding_set_id==embedding_set_id,KnowledgeChunkRow.chunk_set_id==chunk_set_id))
			if vector_count!=chunk_count or matched_count!=chunk_count: raise ValueError("EmbeddingSet未完整覆盖指定ChunkSet")
		if row:
			row.chunk_set_id=chunk_set_id
			row.embedding_set_id=embedding_set_id
		else:
			self.session.add(KnowledgePublicationRow(document_id=document_id,chunk_set_id=chunk_set_id,embedding_set_id=embedding_set_id))
