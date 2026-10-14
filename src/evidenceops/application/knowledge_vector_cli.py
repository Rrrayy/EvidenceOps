"""内部向量验收CLI；不提供上传API，不使用诊断模型配置。"""
import argparse
import json
import os
from pathlib import Path

from evidenceops.application.document_ingestion import DocumentIngestionService
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.connectors.local_document import LocalDocumentLoader
from evidenceops.domain.knowledge import KnowledgeDocument
from evidenceops.domain.knowledge_vectors import EncodingConfig
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.providers.embedding_provider import HttpEmbeddingProvider


def main()->None:
	parser=argparse.ArgumentParser(description="内部知识向量构建、显式发布和精确检索")
	commands=parser.add_subparsers(dest="command",required=True)
	ingest=commands.add_parser("ingest")
	ingest.add_argument("root",type=Path)
	ingest.add_argument("relative_path")
	ingest.add_argument("document_id")
	ingest.add_argument("--title",required=True)
	build=commands.add_parser("build")
	build.add_argument("document_id")
	build.add_argument("chunk_set_id")
	build.add_argument("--budget",type=float,default=60)
	publish=commands.add_parser("publish")
	publish.add_argument("document_id")
	publish.add_argument("embedding_set_id")
	publish.add_argument("--expected-active",default=None)
	search=commands.add_parser("search")
	search.add_argument("document_id")
	search.add_argument("query")
	search.add_argument("--top-k",type=int,default=5)
	search.add_argument("--threshold",type=float,default=None)
	args=parser.parse_args()
	engine=create_database_engine(DatabaseSettings.from_environment())
	try:
		factory=create_session_factory(engine)
		service=VectorKnowledgeService(factory)
		if args.command=="ingest":
			result=DocumentIngestionService(LocalDocumentLoader(args.root)).ingest(KnowledgeDocument(args.document_id,args.title,args.relative_path),args.relative_path)
			with factory.begin() as session: SqlAlchemyKnowledgeRepository(session).save_ingestion(result.document,result.version,result.chunk_set,result.chunks)
			output={"document_id":args.document_id,"version_id":result.version.version_id,"chunk_set_id":result.chunk_set.chunk_set_id,"chunk_count":len(result.chunks)}
		elif args.command=="publish":
			service.publish(args.document_id,args.embedding_set_id,args.expected_active)
			output={"published":args.embedding_set_id}
		else:
			# 编码用途默认相同，模型需要前缀时显式设置并纳入指纹；不能自动猜测供应商规则。
			config=EncodingConfig(provider=os.environ["EMBEDDING_PROVIDER"],deployment=os.environ["EMBEDDING_ENDPOINT"],model=os.environ["EMBEDDING_MODEL"],dimensions=int(os.environ["EMBEDDING_DIMENSIONS"]),revision=os.getenv("EMBEDDING_REVISION","unknown"),document_mode="default",query_mode="default",document_prefix=os.getenv("EMBEDDING_DOCUMENT_PREFIX",""),query_prefix=os.getenv("EMBEDDING_QUERY_PREFIX",""))
			provider=HttpEmbeddingProvider(config,os.environ["EMBEDDING_API_KEY"])
			if args.command=="build":
				output={"embedding_set_id":service.build(args.document_id,args.chunk_set_id,config,provider,budget=args.budget),"config_fingerprint":config.fingerprint,"revision":config.revision}
			else:
				matches=service.search(args.document_id,args.query,provider,top_k=args.top_k,threshold=args.threshold)
				output={"matches":[{"chunk_id":match.chunk.chunk_id,"chunk_set_id":match.chunk.chunk_set.chunk_set_id,"version_id":match.chunk.chunk_set.version_id,"content":match.chunk.content,"heading_path":match.chunk.heading_path,"start_offset":match.chunk.start_offset,"end_offset":match.chunk.end_offset,"score":match.score,"rank":match.rank} for match in matches]}
		print(json.dumps(output,ensure_ascii=False,indent=2))
	finally:
		engine.dispose()


if __name__=="__main__":
	main()
