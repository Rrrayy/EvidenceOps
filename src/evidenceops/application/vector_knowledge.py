"""小语料向量基础层：构建、发布和查询分离，不连接Agent。"""
from time import monotonic
import math
from uuid import uuid4

from sqlalchemy import select
from evidenceops.application.knowledge_embedding import cosine_similarity
from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.domain.knowledge_vectors import EncodingConfig,validate_vectors
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.models import KnowledgeEmbeddingSetRow,KnowledgeVectorRow
from evidenceops.infrastructure.database.vector_repository import VectorRepository


class VectorKnowledgeService:
	def __init__(self,session_factory,max_candidates:int=1000,max_values:int=1000000)->None:
		if type(max_candidates) is not int or max_candidates<1 or type(max_values) is not int or max_values<1: raise ValueError("候选上限无效")
		self.factory=session_factory
		self.max_candidates=max_candidates
		self.max_values=max_values

	def build(self,document_id:str,chunk_set_id:str,config:EncodingConfig,provider,batch_size:int=16,budget:float=60)->str:
		if type(batch_size) is not int or not 1<=batch_size<=128 or not math.isfinite(budget) or budget<=0: raise ValueError("构建预算或批次大小无效")
		if provider.config.fingerprint!=config.fingerprint: raise ValueError("编码器配置不匹配")
		deadline=monotonic()+budget
		with self.factory() as session:
			limit=min(self.max_candidates,self.max_values//config.dimensions)
			chunks=SqlAlchemyKnowledgeRepository(session).load_chunks(document_id,chunk_set_id,limit=limit+1)
		if not chunks: raise ValueError("指定集合没有片段")
		if len(chunks)>self.max_candidates or len(chunks)*config.dimensions>self.max_values: raise ValueError("构建超过候选或向量内存预算")
		set_id="embedding-"+str(uuid4())
		with self.factory.begin() as session: VectorRepository(session).create(set_id,chunk_set_id,config)
		with self.factory.begin() as session: VectorRepository(session).transition(set_id,"pending","building")
		try:
			vectors=[]
			# HTTP调用期间没有Session或事务；每批校验后仍暂存内存，不发布半成品。
			for offset in range(0,len(chunks),batch_size):
				remaining=deadline-monotonic()
				if remaining<=0: raise TimeoutError("向量构建总预算耗尽")
				texts=config.prepare(tuple(chunk.content for chunk in chunks[offset:offset+batch_size]),"document")
				response=provider.encode(texts,"document",remaining)
				vectors.extend(validate_vectors(response,len(texts),config.dimensions))
				if monotonic()>=deadline: raise TimeoutError("向量构建总预算耗尽")
			with self.factory.begin() as session: VectorRepository(session).complete(set_id,chunks,tuple(vectors))
		except Exception as error:
			with self.factory.begin() as session: VectorRepository(session).transition(set_id,"building","failed",type(error).__name__)
			raise
		return set_id

	def publish(self,document_id:str,set_id:str,expected_active:str|None)->None:
		with self.factory.begin() as session: VectorRepository(session).publish(document_id,set_id,expected_active)

	def search(self,document_id:str,query:str,provider,top_k:int=5,threshold:float|None=None,chunk_ids:frozenset[str]|None=None,budget:float=10)->tuple[KnowledgeMatch,...]:
		if not isinstance(query,str) or not query.strip(): raise ValueError("query不能为空")
		if type(top_k) is not int or not 1<=top_k<=50 or not math.isfinite(budget) or budget<=0: raise ValueError("查询预算或top_k无效")
		if threshold is not None and not -1<=threshold<=1: raise ValueError("threshold必须在-1到1之间")
		if chunk_ids is not None and not isinstance(chunk_ids,frozenset): raise ValueError("chunk_ids必须为frozenset或None")
		if chunk_ids==frozenset(): return ()
		deadline=monotonic()+budget
		with self.factory() as session:
			set_id=VectorRepository(session).active(document_id)
			if set_id is None: return ()
			row=session.get(KnowledgeEmbeddingSetRow,set_id)
			if row.status!="ready": raise ValueError("发布集合不是ready")
			config=EncodingConfig(**row.config)
			if provider.config.fingerprint!=config.fingerprint: raise ValueError("查询编码器与发布集合不兼容")
			if row.config_fingerprint!=config.fingerprint: raise ValueError("持久化配置指纹损坏")
			statement=select(KnowledgeVectorRow).where(KnowledgeVectorRow.embedding_set_id==set_id)
			if chunk_ids is not None: statement=statement.where(KnowledgeVectorRow.chunk_id.in_(chunk_ids))
			limit=min(self.max_candidates,self.max_values//config.dimensions)
			rows=session.scalars(statement.order_by(KnowledgeVectorRow.chunk_id).limit(limit+1)).all()
			if len(rows)>limit: raise ValueError("查询超过候选或向量内存预算")
			if not rows: return ()
			chunks=SqlAlchemyKnowledgeRepository(session).load_chunks(document_id,row.chunk_set_id,frozenset(item.chunk_id for item in rows),limit=limit+1)
			by_id={chunk.chunk_id:chunk for chunk in chunks}
			candidates=tuple((by_id[item.chunk_id],tuple(item.vector)) for item in rows)
		remaining=deadline-monotonic()
		if remaining<=0: raise TimeoutError("查询预算耗尽")
		vector=validate_vectors(provider.encode(config.prepare((query,),"query"),"query",remaining),1,config.dimensions)[0]
		if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
		scored=[]
		for chunk,stored in candidates:
			validated=validate_vectors((stored,),1,config.dimensions)[0]
			score=cosine_similarity(vector,validated)
			if threshold is None or score>=threshold: scored.append((score,chunk))
		scored.sort(key=lambda item:(-item[0],item[1].chunk_id))
		if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
		return tuple(KnowledgeMatch(chunk,score,index+1,"exact-cosine-v1") for index,(score,chunk) in enumerate(scored[:top_k]))
