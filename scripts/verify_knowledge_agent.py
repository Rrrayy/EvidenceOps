"""真实Embedding+PostgreSQL验收；生成模型为确定性替身，不冒充真实故障诊断。"""
import json
from uuid import uuid4

from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.diagnosis_history import load_diagnosis_history
from evidenceops.application.event_history import load_event_page
from evidenceops.application.history_response import history_response
from evidenceops.application.model_protocol import ModelProviderError,StructuredFinalAnswer,ToolCall
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence
from evidenceops.infrastructure.database.session import DatabaseSettings,create_database_engine,create_session_factory
from evidenceops.infrastructure.knowledge_tools import configured_knowledge_tools
from evidenceops.infrastructure.providers.mock_provider import MockProvider


def main():
	engine=create_database_engine(DatabaseSettings.from_environment())
	factory=create_session_factory(engine)
	try:
		for fail in (False,True):
			persistence=SqlAlchemyDiagnosisPersistence(factory)
			tools=configured_knowledge_tools(persistence)
			if not tools: raise RuntimeError("请先启用EVIDENCEOPS_KNOWLEDGE_ENABLED并配置Embedding")
			visible=[]
			def final(request):
				fragments=json.loads(request.messages[-1]["content"])["data"]["matches"]
				assert fragments,"验收查询应命中已发布手册"
				visible.extend(fragments)
				if fail: raise ModelProviderError("MODEL_PROTOCOL_ERROR","验收注入的第二轮协议错误")
				ids=[fragment["evidence_id"] for fragment in fragments]
				return StructuredFinalAnswer({"root_cause":{"text":"链路验收演示：仅凭手册无法确认实际根因","evidence_ids":ids},
					"recommendations":[{"text":"演示：按手册补查RPC延迟和线程池观测","evidence_ids":ids}],
					"confidence":0.1,"limitations":"真实Embedding，确定性生成替身；样本不是权威手册，不是故障诊断"})
			provider=MockProvider((ToolCall("knowledge-acceptance","search_knowledge",{"query":"RPC超时与线程池饱和应该补查什么","top_k":3}),final))
			assembly=build_agent_diagnosis_assembly(provider,"acceptance-mock",tools,"order-service",diagnosis_persistence=persistence)
			try:
				result=assembly.diagnosis_service.execute("req-knowledge-acceptance-"+str(uuid4()),"真实Embedding知识引用链路验收演示")
				history=history_response(load_diagnosis_history(persistence,result.run.run_id))
				assert len(history["evidences"])==len(visible)>0
				by_id={item["evidence_id"]:item for item in history["evidences"]}
				for fragment in visible:
					saved=by_id[fragment["evidence_id"]]
					assert saved["content_snapshot"]==fragment["content"]
					assert saved["source_metadata"]==fragment["metadata"]
				assert len(history["execution_records"])==3
				assert history["status"]==("failed" if fail else "succeeded")
				assert history["error_code"]==("MODEL_PROTOCOL_ERROR" if fail else None)
				assert (history["report"] is None)==fail
				events=load_event_page(persistence,result.run.run_id).events
				assert events[-1]["event"]==("run_failed" if fail else "run_completed")
				assert events[-1]["data"]["result"]["evidences"][0]["content_snapshot"] in [item["content"] for item in visible]
				print(json.dumps({"run_id":result.run.run_id,"status":history["status"],"error_code":history["error_code"],
					"evidence_count":len(visible),"embedding_set_id":visible[0]["metadata"]["embedding_set_id"],
					"verified":"真实Embedding、模型可见引用、数据库正文、历史回查、持久化终止事件；生成模型为替身"},ensure_ascii=False))
			finally: assembly.close()
	finally: engine.dispose()


if __name__=="__main__": main()
