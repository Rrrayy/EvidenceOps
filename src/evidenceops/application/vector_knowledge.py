"""小语料向量服务：独立构建发布，支持受控文档清单的精确检索。"""
from time import monotonic
import math
from uuid import uuid4

from sqlalchemy import select
from evidenceops.application.knowledge_embedding import cosine_similarity
from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.application.hybrid_knowledge import fuse_rankings,keyword_ranking
from evidenceops.application.bm25_knowledge import bm25_ranking
from evidenceops.domain.knowledge_vectors import EncodingConfig,validate_vectors
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.models import KnowledgeChunkSetRow,KnowledgeEmbeddingSetRow,KnowledgeVectorRow,KnowledgeVersionRow
from evidenceops.infrastructure.database.vector_repository import PublicationConflict,PublicationPointer,VectorRepository


class VectorKnowledgeService:
	def __init__(self,session_factory,max_candidates:int=1000,max_values:int=1000000,vector_search_mode:str="exact")->None:
		if type(max_candidates) is not int or max_candidates<1 or type(max_values) is not int or max_values<1: raise ValueError("候选上限无效")
		if vector_search_mode not in ("auto","exact","hnsw","json_exact"): raise ValueError("vector_search_mode无效")
		self.factory=session_factory
		self.max_candidates=max_candidates
		self.max_values=max_values
		self.vector_search_mode=vector_search_mode

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
		bind=self.factory.kw.get("bind")
		if bind is not None and bind.dialect.name=="postgresql" and config.dimensions<=2000:
			try: VectorRepository.ensure_hnsw_dimension_index(bind,config.dimensions,config.fingerprint)
			except Exception as error: raise RuntimeError("EmbeddingSet已ready，但HNSW索引未完成；可重试索引构建") from error
		return set_id

	def publish_chunk_set(self,document_id:str,chunk_set_id:str,embedding_set_id:str|None=None,
		expected_active:PublicationPointer|None=None)->None:
		with self.factory.begin() as session:
			VectorRepository(session).publish(document_id,chunk_set_id,embedding_set_id,expected_active)

	def publish(self,document_id:str,set_id:str,expected_active:str|None)->None:
		with self.factory() as session:
			encoding=session.get(KnowledgeEmbeddingSetRow,set_id)
			if encoding is None: raise ValueError("EmbeddingSet不存在")
			repository=VectorRepository(session)
			current=repository.active_publication(document_id)
			if (current.embedding_set_id if current else None)!=expected_active:
				raise PublicationConflict("发布指针已变化，请重新验收后发布")
		self.publish_chunk_set(document_id,encoding.chunk_set_id,set_id,current)

	def search(self,document_id:str,query:str,provider=None,top_k:int=5,threshold:float|None=None,chunk_ids:frozenset[str]|None=None,budget:float=10)->tuple[KnowledgeMatch,...]:
		return self.search_many((document_id,),query,provider,top_k,threshold,chunk_ids,budget)

	def search_many(self,document_ids:tuple[str,...],query:str,provider=None,top_k:int=5,threshold:float|None=None,
		chunk_ids:frozenset[str]|None=None,budget:float=10,method:str="cosine",candidate_k:int=10)->tuple[KnowledgeMatch,...]:
		if method not in ("cosine","keyword","bm25","hybrid","hybrid_bm25"): raise ValueError("检索方法无效")
		if type(candidate_k) is not int or not 1<=candidate_k<=50: raise ValueError("每路候选必须在1到50之间")
		if type(top_k) is not int or not 1<=top_k<=50: raise ValueError("top_k必须在1到50之间")
		if method in ("hybrid","hybrid_bm25") and candidate_k<top_k: raise ValueError("每路候选不能小于最终top_k")
		if method in ("keyword","bm25","hybrid","hybrid_bm25") and threshold is not None: raise ValueError("关键词检索不接受cosine阈值")
		if not isinstance(document_ids,tuple) or not 1<=len(document_ids)<=16:
			raise ValueError("文档清单必须包含1到16个不同身份")
		if any(not isinstance(identity,str) or not identity.strip() for identity in document_ids): raise ValueError("文档身份不能为空")
		if len(set(document_ids))!=len(document_ids): raise ValueError("文档身份不能重复")
		if not isinstance(query,str) or not query.strip(): raise ValueError("query不能为空")
		if type(top_k) is not int or not 1<=top_k<=50 or not math.isfinite(budget) or budget<=0: raise ValueError("查询预算或top_k无效")
		if threshold is not None and (type(threshold) not in (float,int) or not math.isfinite(threshold) or not -1<=threshold<=1): raise ValueError("threshold必须在-1到1之间")
		if chunk_ids is not None and not isinstance(chunk_ids,frozenset): raise ValueError("chunk_ids必须为frozenset或None")
		if chunk_ids==frozenset(): return ()
		lexical_only=method in ("keyword","bm25")
		if not lexical_only and provider is None: raise ValueError("该检索模式需要Embedding Provider")
		config=provider.config if provider is not None else None
		deadline=monotonic()+budget
		candidates=[]
		postgres_sets=[]
		vector_mode=self.vector_search_mode
		limit=self.max_candidates if lexical_only else min(self.max_candidates,self.max_values//config.dimensions)
		with self.factory() as session:
			postgres=session.bind.dialect.name=="postgresql"
			if vector_mode=="auto": vector_mode="hnsw" if postgres else "exact"
			if not lexical_only and vector_mode=="hnsw" and not postgres:
				raise ValueError("HNSW检索需要PostgreSQL + pgvector")
			for document_id in sorted(document_ids):
				publication=VectorRepository(session).active_publication(document_id)
				if publication is None:
					if len(document_ids)==1: return ()
					raise ValueError("配置的知识文档尚未发布："+document_id)
				set_id=publication.embedding_set_id
				remaining_limit=limit-len(candidates)
				if lexical_only:
					chunks=SqlAlchemyKnowledgeRepository(session).load_chunks(document_id,publication.chunk_set_id,chunk_ids,remaining_limit+1)
					if len(chunks)>remaining_limit: raise ValueError("查询超过候选预算")
					if not chunks: continue
					version=session.get(KnowledgeVersionRow,chunks[0].chunk_set.version_id)
					if version is None: raise ValueError("发布片段缺少文档版本")
					candidates.extend((chunk,None,None,None,document_id,version.source_ref) for chunk in chunks)
					continue
				if set_id is None: raise ValueError("发布ChunkSet没有可用EmbeddingSet")
				row=session.get(KnowledgeEmbeddingSetRow,set_id)
				if row is None or row.status!="ready": raise ValueError("发布向量集合不是ready")
				if row.chunk_set_id!=publication.chunk_set_id: raise ValueError("发布EmbeddingSet与ChunkSet不匹配")
				stored_config=EncodingConfig(**row.config)
				if config.fingerprint!=stored_config.fingerprint: raise ValueError("查询编码器与发布集合不兼容")
				if row.config_fingerprint!=stored_config.fingerprint: raise ValueError("持久化配置指纹损坏")
				if postgres and vector_mode!="json_exact":
					chunk_set=session.get(KnowledgeChunkSetRow,publication.chunk_set_id)
					version=session.get(KnowledgeVersionRow,chunk_set.version_id) if chunk_set else None
					if version is None: raise ValueError("发布片段缺少文档版本")
					postgres_sets.append((document_id,publication.chunk_set_id,set_id,row.config_fingerprint,version.source_ref))
					continue
				statement=select(KnowledgeVectorRow).where(KnowledgeVectorRow.embedding_set_id==set_id)
				if chunk_ids is not None: statement=statement.where(KnowledgeVectorRow.chunk_id.in_(chunk_ids))
				remaining_limit=limit-len(candidates)
				rows=session.scalars(statement.order_by(KnowledgeVectorRow.chunk_id).limit(remaining_limit+1)).all()
				if len(rows)>remaining_limit: raise ValueError("查询超过候选或向量内存预算")
				if not rows: continue
				chunks=SqlAlchemyKnowledgeRepository(session).load_chunks(document_id,publication.chunk_set_id,frozenset(item.chunk_id for item in rows),limit=len(rows)+1)
				by_id={chunk.chunk_id:chunk for chunk in chunks}
				version=session.get(KnowledgeVersionRow,chunks[0].chunk_set.version_id)
				candidates.extend((by_id[item.chunk_id],tuple(item.vector),set_id,row.config_fingerprint,document_id,version.source_ref) for item in rows)
		if not candidates and not postgres_sets: return ()
		remaining=deadline-monotonic()
		if remaining<=0: raise TimeoutError("查询预算耗尽")
		if method in ("bm25","keyword"):
			matches=tuple(KnowledgeMatch(chunk,0,index+1,embedding_set_id=set_id,config_fingerprint=config_fingerprint,document_id=document_id,source_ref=source_ref)
				for index,(chunk,stored,set_id,config_fingerprint,document_id,source_ref) in enumerate(candidates))
			result=bm25_ranking(matches,query,top_k) if method=="bm25" else keyword_ranking(matches,query,top_k)
			if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
			return result
		vector=validate_vectors(provider.encode(config.prepare((query,),"query"),"query",remaining),1,config.dimensions)[0]
		if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
		if postgres_sets:
			if vector_mode=="hnsw" and config.dimensions>2000:
				raise ValueError("当前维度超过HNSW向量索引上限2000，请改用EVIDENCEOPS_KNOWLEDGE_VECTOR_SEARCH=exact")
			requested=self.max_candidates if threshold is not None else (candidate_k if method in ("hybrid","hybrid_bm25") else top_k)
			ranked=self._search_postgres(postgres_sets,vector,config.dimensions,min(limit,requested),
				chunk_ids,threshold,vector_mode)
			if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
			if method=="cosine": return ranked[:top_k]
			keyword=keyword_ranking(ranked,query,candidate_k) if method=="hybrid" else bm25_ranking(ranked,query,candidate_k)
			result=fuse_rankings(ranked[:candidate_k],keyword,top_k,keyword_name="keyword" if method=="hybrid" else "bm25")
			if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
			return result
		scored=[]
		# 所有候选编码配置相同，只编码一次查询；全局预算不能按文档重置。
		for chunk,stored,set_id,config_fingerprint,document_id,source_ref in candidates:
			validated=validate_vectors((stored,),1,config.dimensions)[0]
			score=cosine_similarity(vector,validated)
			if threshold is None or score>=threshold: scored.append((score,chunk,set_id,config_fingerprint,document_id,source_ref))
		scored.sort(key=lambda item:(-item[0],item[1].chunk_id))
		if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
		retrieval_method="json-exact-cosine-v1" if vector_mode=="json_exact" else "exact-cosine-v1"
		ranked=tuple(KnowledgeMatch(chunk,score,index+1,retrieval_method,set_id,config_fingerprint,document_id,source_ref)
			for index,(score,chunk,set_id,config_fingerprint,document_id,source_ref) in enumerate(scored))
		if method=="cosine": return ranked[:top_k]
		# 两路来自已加载的同一发布集合，不在网络等待后重新读取指针。
		keyword=keyword_ranking(ranked,query,candidate_k) if method=="hybrid" else bm25_ranking(ranked,query,candidate_k)
		result=fuse_rankings(ranked[:candidate_k],keyword,top_k,keyword_name="keyword" if method=="hybrid" else "bm25")
		if monotonic()>=deadline: raise TimeoutError("查询预算耗尽")
		return result

	def _search_postgres(self,sets,query_vector,dimensions,limit,chunk_ids,threshold,mode):
		if mode=="hnsw" and dimensions>2000:
			raise ValueError("当前维度超过HNSW向量索引上限2000，请改用EVIDENCEOPS_KNOWLEDGE_VECTOR_SEARCH=exact")
		set_ids=tuple(item[2] for item in sets)
		fingerprints={item[3] for item in sets}
		if len(fingerprints)!=1: raise ValueError("一次向量查询不能混用多个Embedding配置")
		config_fingerprint=next(iter(fingerprints))
		with self.factory() as session:
			ranked=VectorRepository(session).search(set_ids,dimensions,config_fingerprint,query_vector,limit,chunk_ids,mode)
			metadata={}
			for document_id,chunk_set_id,set_id,fingerprint,source_ref in sets:
				selected=frozenset(identity for row_set_id,identity,_ in ranked if row_set_id==set_id)
				if not selected: continue
				chunks=SqlAlchemyKnowledgeRepository(session).load_chunks(
					document_id,chunk_set_id,selected,limit=len(selected)+1)
				for chunk in chunks:
					metadata[(set_id,chunk.chunk_id)]=(chunk,set_id,fingerprint,document_id,source_ref)
		matches=[]
		for set_id,identity,score in sorted(ranked,key=lambda item:(-item[2],item[1],item[0])):
			item=metadata.get((set_id,identity))
			if item is None: raise ValueError("向量查询返回不属于发布ChunkSet的片段")
			if threshold is not None and score<threshold: continue
			chunk,set_id,fingerprint,document_id,source_ref=item
			matches.append(KnowledgeMatch(chunk,score,len(matches)+1,
				"hnsw-cosine-v1" if mode=="hnsw" else "exact-cosine-pg-v1",
				set_id,fingerprint,document_id,source_ref))
		return tuple(matches)
