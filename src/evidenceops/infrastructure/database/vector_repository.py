from dataclasses import asdict
from sqlalchemy import select

from evidenceops.domain.knowledge_vectors import EncodingConfig,validate_vectors
from evidenceops.infrastructure.database.models import KnowledgeDocumentRow,KnowledgeEmbeddingSetRow,KnowledgePublicationRow,KnowledgeVectorRow,KnowledgeChunkSetRow,KnowledgeVersionRow
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository


class PublicationConflict(RuntimeError):
	pass


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
		row=self.session.get(KnowledgePublicationRow,document_id)
		return row.embedding_set_id if row else None

	def publish(self,document_id:str,set_id:str,expected_active:str|None)->None:
		# 锁逻辑文档而非可空指针，首次发布也能串行化；调用方必须在短事务内使用。
		document=self.session.scalar(select(KnowledgeDocumentRow).where(KnowledgeDocumentRow.document_id==document_id).with_for_update())
		if document is None: raise ValueError("文档不存在")
		row=self.session.get(KnowledgePublicationRow,document_id,populate_existing=True)
		if (row.embedding_set_id if row else None)!=expected_active: raise PublicationConflict("发布指针已变化，请重新验收后发布")
		building=self.session.get(KnowledgeEmbeddingSetRow,set_id)
		if building is None or building.status!="ready": raise ValueError("仅ready集合可发布")
		chunk_set=self.session.get(KnowledgeChunkSetRow,building.chunk_set_id)
		version=self.session.get(KnowledgeVersionRow,chunk_set.version_id)
		if version.document_id!=document_id: raise ValueError("集合不属于文档")
		if row: row.embedding_set_id=set_id
		else: self.session.add(KnowledgePublicationRow(document_id=document_id,embedding_set_id=set_id))
