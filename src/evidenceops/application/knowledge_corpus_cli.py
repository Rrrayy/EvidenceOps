"""维护小型练习语料；每份文档独立构建和发布，失败不会覆盖该文档旧指针。"""
import argparse
import json
from pathlib import Path

from evidenceops.application.document_ingestion import DocumentIngestionService
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.connectors.local_document import LocalDocumentLoader
from evidenceops.domain.knowledge import KnowledgeDocument
from evidenceops.infrastructure.database.knowledge_repository import SqlAlchemyKnowledgeRepository
from evidenceops.infrastructure.database.models import KnowledgeEmbeddingSetRow
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.database.vector_repository import VectorRepository
from evidenceops.infrastructure.knowledge_tools import configured_embedding_provider


def read_manifest(path:Path)->dict:
	if path.stat().st_size>100000: raise ValueError("语料清单过大")
	manifest=json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(manifest,dict): raise ValueError("语料清单必须为JSON对象")
	documents=manifest.get("documents")
	if not isinstance(documents,list) or not 1<=len(documents)<=16: raise ValueError("清单需要1到16份文档")
	seen=set()
	for item in documents:
		if not isinstance(item,dict) or set(item)!={"document_id","path","title"}: raise ValueError("文档清单字段无效")
		if any(not isinstance(value,str) or not value.strip() for value in item.values()): raise ValueError("文档清单字段不能为空")
		if item["document_id"] in seen: raise ValueError("文档身份重复")
		seen.add(item["document_id"])
	return manifest


def prepare_corpus(factory,manifest_path:Path,provider,publish:bool=False)->list[dict]:
	manifest=read_manifest(manifest_path)
	ingestion=DocumentIngestionService(LocalDocumentLoader(manifest_path.resolve().parent))
	# 先验证所有输入再调用供应商，坏文件不会留下部分摄取结果。
	inputs=tuple(ingestion.ingest(KnowledgeDocument(item["document_id"],item["title"],item["path"]),item["path"]) for item in manifest["documents"])
	service=VectorKnowledgeService(factory)
	results=[]
	for data in inputs:
		with factory.begin() as session:
			SqlAlchemyKnowledgeRepository(session).save_ingestion(data.document,data.version,data.chunk_set,data.chunks)
		with factory() as session:
			previous=VectorRepository(session).active(data.document.document_id)
			active=session.get(KnowledgeEmbeddingSetRow,previous) if previous else None
			unchanged=bool(active and active.status=="ready" and active.chunk_set_id==data.chunk_set.chunk_set_id
				and active.config_fingerprint==provider.config.fingerprint)
		set_id=previous if unchanged else service.build(data.document.document_id,data.chunk_set.chunk_set_id,provider.config,provider)
		if publish and not unchanged: service.publish(data.document.document_id,set_id,previous)
		results.append({"document_id":data.document.document_id,"chunk_count":len(data.chunks),"embedding_set_id":set_id,
			"published":publish or unchanged,"reused":unchanged})
	return results


def main():
	parser=argparse.ArgumentParser(description="练习知识库构建发布与固定检索基线")
	parser.add_argument("command",choices=("prepare","evaluate"))
	parser.add_argument("manifest",type=Path)
	parser.add_argument("--publish",action="store_true",help="显式切换各文档默认指针；不是整库原子发布")
	parser.add_argument("--cases",type=Path)
	args=parser.parse_args()
	manifest=read_manifest(args.manifest)
	provider=configured_embedding_provider()
	engine=create_database_engine(DatabaseSettings.from_environment())
	try:
		factory=create_session_factory(engine)
		if args.command=="prepare":
			print(json.dumps({"documents":prepare_corpus(factory,args.manifest,provider,args.publish)},ensure_ascii=False,indent=2))
		else:
			if args.publish: parser.error("evaluate不支持--publish")
			case_path=args.cases or args.manifest.parent/"acceptance_cases.json"
			if case_path.stat().st_size>100000: raise ValueError("案例集过大")
			cases=json.loads(case_path.read_text(encoding="utf-8-sig"))["cases"]
			if not isinstance(cases,list) or not 1<=len(cases)<=100: raise ValueError("案例数量无效")
			service=VectorKnowledgeService(factory)
			identities=tuple(item["document_id"] for item in manifest["documents"])
			results=[]
			for case in cases:
				matches=service.search_many(identities,case["query"],provider,top_k=3)
				documents=[match.document_id for match in matches]
				expected=case["expected_document_id"]
				results.append({"case_id":case["case_id"],"expected_document_id":expected,"documents":documents,
					"top1_hit":documents[0]==expected if expected and documents else (False if expected else None),
					"top3_hit":expected in documents if expected else None})
			positive=[item for item in results if item["expected_document_id"]]
			print(json.dumps({"positive_cases":len(positive),"top1_hits":sum(item["top1_hit"] for item in positive),
				"top3_hits":sum(item["top3_hit"] for item in positive),"results":results,
				"limitations":"仅文档级命中；负例不要求无阈值Top-K为空，不评估生成质量"},ensure_ascii=False,indent=2))
	finally: engine.dispose()


if __name__=="__main__": main()
