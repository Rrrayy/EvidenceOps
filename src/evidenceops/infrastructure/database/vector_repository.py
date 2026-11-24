from dataclasses import asdict
from typing import NamedTuple
from sqlalchemy import cast,func,literal_column,select,text
from sqlalchemy.engine import Engine
from pgvector.sqlalchemy import Vector

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

	@staticmethod
	def _index_name(dimensions:int,config_fingerprint:str)->str:
		return f"ix_kcv_hnsw_{dimensions}_{config_fingerprint[:24]}"

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
			self.session.add(KnowledgeVectorRow(embedding_set_id=set_id,chunk_id=chunk.chunk_id,
				dimensions=config.dimensions,config_fingerprint=config.fingerprint,vector=list(vector),embedding=list(vector)))
		self.session.flush()
		self.transition(set_id,"building","ready")

	@staticmethod
	def ensure_hnsw_dimension_index(engine:Engine,dimensions:int,config_fingerprint:str)->str:
		if type(dimensions) is not int or not 1<=dimensions<=2000:
			raise ValueError("pgvector HNSW vector索引仅支持1到2000维；请使用精确检索")
		if not isinstance(config_fingerprint,str) or len(config_fingerprint)!=64 or any(character not in "0123456789abcdef" for character in config_fingerprint):
			raise ValueError("config_fingerprint必须是64位小写SHA-256")
		if engine.dialect.name!="postgresql": raise ValueError("HNSW索引只支持PostgreSQL")
		name=VectorRepository._index_name(dimensions,config_fingerprint)
		with engine.connect() as connection:
			connection=connection.execution_options(isolation_level="AUTOCOMMIT")
			connection.execute(text("SELECT pg_advisory_lock(hashtext('evidenceops.hnsw.dimension'),:dimensions)"),
				{"dimensions":dimensions})
			try:
				valid=connection.scalar(text(
					"SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
					"JOIN pg_namespace n ON n.oid=c.relnamespace "
					"WHERE n.nspname=current_schema() AND c.relname=:name"),{"name":name})
				if valid is False:
					connection.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
				connection.execute(text(
					f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON knowledge_chunk_vectors "
					f"USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops) WITH (m=16,ef_construction=64) "
					f"WHERE dimensions={dimensions} AND config_fingerprint='{config_fingerprint}'"))
				valid=connection.scalar(text(
					"SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
					"JOIN pg_namespace n ON n.oid=c.relnamespace "
					"WHERE n.nspname=current_schema() AND c.relname=:name"),{"name":name})
				if not valid: raise RuntimeError("HNSW索引构建未完成")
			finally:
				connection.execute(text("SELECT pg_advisory_unlock(hashtext('evidenceops.hnsw.dimension'),:dimensions)"),
					{"dimensions":dimensions})
		return name

	def search(self,embedding_set_ids:tuple[str,...],dimensions:int,config_fingerprint:str,query_vector:tuple[float,...],limit:int,
		chunk_ids:frozenset[str]|None=None,mode:str="exact")->tuple[tuple[str,str,float],...]:
		if mode not in ("exact","hnsw"): raise ValueError("向量检索模式无效")
		if not embedding_set_ids or type(limit) is not int or limit<1: raise ValueError("向量检索参数无效")
		if len(query_vector)!=dimensions: raise ValueError("查询向量维度不匹配")
		if not isinstance(config_fingerprint,str) or len(config_fingerprint)!=64 or any(character not in "0123456789abcdef" for character in config_fingerprint):
			raise ValueError("config_fingerprint必须是64位小写SHA-256")
		if mode=="hnsw":
			if dimensions>2000: raise ValueError("当前维度不支持HNSW，请使用精确检索")
			index_name=self._index_name(dimensions,config_fingerprint)
			valid=self.session.scalar(text(
				"SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
				"JOIN pg_namespace n ON n.oid=c.relnamespace "
				"WHERE n.nspname=current_schema() AND c.relname=:name"),{"name":index_name})
			if not valid: raise ValueError("缺少有效HNSW索引，请先构建该维度索引")
			self.session.execute(text("SET LOCAL hnsw.iterative_scan='strict_order'"))
		else:
			self.session.execute(text("SET LOCAL enable_indexscan=off"))
			self.session.execute(text("SET LOCAL enable_bitmapscan=off"))
		distance=cast(KnowledgeVectorRow.embedding,Vector(dimensions)).cosine_distance(list(query_vector))
		statement=select(KnowledgeVectorRow.embedding_set_id,KnowledgeVectorRow.chunk_id,(1-distance).label("score")).where(
			KnowledgeVectorRow.embedding_set_id.in_(embedding_set_ids),
			KnowledgeVectorRow.dimensions==literal_column(str(dimensions)),
			KnowledgeVectorRow.config_fingerprint==literal_column(f"'{config_fingerprint}'"))
		if chunk_ids is not None: statement=statement.where(KnowledgeVectorRow.chunk_id.in_(chunk_ids))
		ordering=(distance,) if mode=="hnsw" else (distance,KnowledgeVectorRow.chunk_id)
		rows=self.session.execute(statement.order_by(*ordering).limit(limit)).all()
		return tuple((row.embedding_set_id,row.chunk_id,max(-1.0,min(1.0,float(row.score)))) for row in rows)

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
