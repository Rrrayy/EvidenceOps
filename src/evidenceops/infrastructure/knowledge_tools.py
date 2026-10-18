"""按显式配置启用知识工具；Embedding与诊断模型配置完全分离。"""
import os

from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.connectors.knowledge_search import build_knowledge_search_tool
from evidenceops.domain.knowledge_vectors import EncodingConfig
from evidenceops.infrastructure.providers.embedding_provider import HttpEmbeddingProvider


def configured_embedding_provider()->HttpEmbeddingProvider:
	config=EncodingConfig(provider=os.environ["EMBEDDING_PROVIDER"],deployment=os.environ["EMBEDDING_ENDPOINT"],
		model=os.environ["EMBEDDING_MODEL"],dimensions=int(os.environ["EMBEDDING_DIMENSIONS"]),
		revision=os.getenv("EMBEDDING_REVISION","unknown"),document_mode="default",query_mode="default",
		document_prefix=os.getenv("EMBEDDING_DOCUMENT_PREFIX",""),query_prefix=os.getenv("EMBEDDING_QUERY_PREFIX",""))
	return HttpEmbeddingProvider(config,os.getenv("EMBEDDING_API_KEY") or os.environ["DASHSCOPE_API_KEY"],timeout=8)


def configured_knowledge_tools(persistence)->tuple:
	if os.getenv("EVIDENCEOPS_KNOWLEDGE_ENABLED","false").strip().lower()!="true": return ()
	if persistence is None or not hasattr(persistence,"_session_factory"):
		raise ValueError("知识检索需要SQLAlchemy持久化，不能使用memory模式")
	provider=configured_embedding_provider()
	document_ids=tuple(identity.strip() for identity in os.getenv("EVIDENCEOPS_KNOWLEDGE_DOCUMENT_IDS",os.getenv("EVIDENCEOPS_KNOWLEDGE_DOCUMENT_ID","")).split(","))
	if not 1<=len(document_ids)<=16 or any(not identity for identity in document_ids) or len(set(document_ids))!=len(document_ids):
		raise ValueError("知识文档清单必须包含1到16个不同非空身份")
	service=VectorKnowledgeService(persistence._session_factory)
	method=os.getenv("EVIDENCEOPS_KNOWLEDGE_RETRIEVAL","cosine").strip().lower()
	candidate_k=int(os.getenv("EVIDENCEOPS_KNOWLEDGE_CANDIDATE_K","10"))
	if method not in ("cosine","keyword","bm25","hybrid","hybrid_bm25") or not 5<=candidate_k<=50: raise ValueError("检索模式或候选数无效，候选数应在5到50之间")
	def search(query,top_k,budget):
		return service.search_many(document_ids,query,provider,top_k=top_k,budget=budget,method=method,candidate_k=candidate_k)
	return (build_knowledge_search_tool(search),)
