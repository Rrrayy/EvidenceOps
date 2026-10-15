import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.diagnosis_draft import InsufficientEvidence
from evidenceops.application.diagnosis_history import load_diagnosis_history
from evidenceops.application.event_history import load_event_page
from evidenceops.application.history_response import history_response
from evidenceops.application.knowledge_corpus_cli import prepare_corpus,read_manifest
from evidenceops.application.model_protocol import StructuredFinalAnswer,ToolCall
from evidenceops.application.vector_knowledge import VectorKnowledgeService
from evidenceops.connectors.knowledge_search import build_knowledge_search_tool
from evidenceops.domain.knowledge_vectors import EncodingConfig
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from test_knowledge_agent import persistence,matches
from test_vector_knowledge import factory,setup_document,TestEncoder


def insufficient():
	return {"outcome":"insufficient_evidence","reason":"资料不适用于该错误，缺少现场观测",
		"missing_information":["完整错误栈","运行环境与版本"]}


@pytest.mark.parametrize("empty",[True,False])
def test_insufficient_is_distinct_from_protocol_failure_and_survives_history(persistence,empty):
	found=() if empty else matches()
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge","search_knowledge",{"query":"React hydration"}),
		StructuredFinalAnswer(insufficient()))),"test",(build_knowledge_search_tool(lambda *args,**kwargs:found),),
		"order-service",diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute("req-insufficient","React页面报错且没有相应知识资料")
		assert result.run.status.value=="failed" and result.run.error_code=="EVIDENCE_INSUFFICIENT"
		assert result.report is None and len(result.evidences)==len(found)
		assert result.error_detail["missing_information"]==insufficient()["missing_information"]
		history=history_response(load_diagnosis_history(persistence,result.run.run_id))
		terminal=load_event_page(persistence,result.run.run_id).events[-1]
		assert history["error_detail"]==terminal["data"]["result"]["error_detail"]==result.error_detail
		assert len(history["execution_records"])==3
	finally: assembly.close()


@pytest.mark.parametrize("change",[{"root_cause":{"text":"fake","evidence_ids":[]}},
	{"reason":" "},{"missing_information":[]},{"missing_information":["x"*501]},
	{"reason":"x"*2001},{"outcome":"unknown"}])
def test_insufficient_schema_cannot_bypass_claim_validation(change):
	with pytest.raises(ValueError): InsufficientEvidence.from_mapping({**insufficient(),**change})


def test_invalid_insufficient_result_retains_snapshots(persistence):
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge","search_knowledge",{"query":"RPC"}),
		StructuredFinalAnswer({**insufficient(),"root_cause":"未经引用的根因"}))),"test",
		(build_knowledge_search_tool(lambda *args,**kwargs:matches()),),"order-service",diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute("req-invalid","返回混合格式的验收")
		assert result.run.error_code=="MODEL_PROTOCOL_ERROR" and result.evidences and result.report is None
	finally: assembly.close()


def test_insufficient_sse_and_http_history(persistence):
	from fastapi.testclient import TestClient
	from evidenceops.api.agent_diagnosis import create_app
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall("knowledge","search_knowledge",{"query":"React"}),
		StructuredFinalAnswer(insufficient()))),"test",(build_knowledge_search_tool(lambda *args,**kwargs:matches()),),
		"order-service",diagnosis_persistence=persistence)
	with TestClient(create_app(assembly)) as client:
		response=client.post("/api/v1/agent/diagnosis/stream",json={"description":"React hydration验收"})
		events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
		result=events[-1]["data"]["result"]
		assert events[-1]["event"]=="run_failed" and result["error_code"]=="EVIDENCE_INSUFFICIENT"
		history=client.get("/api/v1/agent/runs/"+result["run_id"]).json()
		assert history["error_detail"]==result["error_detail"] and history["report"] is None


def test_multi_document_query_once_global_ranking_filter_and_limits(factory):
	first,set_one,chunks_one=setup_document(factory)
	second,set_two,chunks_two=setup_document(factory)
	config=EncodingConfig("test","test:local","test-v1",2)
	encoder=TestEncoder(config)
	service=VectorKnowledgeService(factory)
	for document,chunk_set in ((first,set_one),(second,set_two)):
		identity=service.build(document.document_id,chunk_set.chunk_set_id,config,encoder)
		service.publish(document.document_id,identity,None)
	encoder.calls=0
	identities=(first.document_id,second.document_id)
	result=service.search_many(identities,"RPC",encoder,top_k=4)
	assert encoder.calls==1 and len(result)==4
	assert {match.document_id for match in result}==set(identities)
	assert [match.rank for match in result]==[1,2,3,4]
	assert [match.score for match in result]==sorted((match.score for match in result),reverse=True)
	assert service.search_many(identities,"RPC",encoder,chunk_ids=frozenset())==()
	filtered=service.search_many(identities,"RPC",encoder,chunk_ids=frozenset([chunks_two[0].chunk_id]))
	assert len(filtered)==1 and filtered[0].document_id==second.document_id
	with pytest.raises(ValueError,match="预算"):
		VectorKnowledgeService(factory,max_candidates=3).search_many(identities,"RPC",encoder)
	with pytest.raises(ValueError,match="兼容"):
		service.search_many(identities,"RPC",TestEncoder(replace(config,model="wrong")))
	with pytest.raises(ValueError,match="尚未发布"):
		service.search_many((first.document_id,"missing-"+str(uuid4())),"RPC",encoder)


def test_sample_manifest_and_prepare_idempotence_and_failure_retains_old(factory,tmp_path):
	manifest_path=Path(__file__).parents[1]/"samples"/"knowledge"/"manifest.json"
	manifest=read_manifest(manifest_path)
	assert len(manifest["documents"])==7
	# PostgreSQL用例也必须使用独立身份，不能覆盖本机真实语料的发布指针。
	for item in manifest["documents"]:
		(tmp_path/item["path"]).write_text((manifest_path.parent/item["path"]).read_text(encoding="utf-8"),encoding="utf-8")
		item["document_id"]="corpus-test-"+str(uuid4())
	manifest_path=tmp_path/"manifest.json"
	manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")
	config=EncodingConfig("test","test:local","test-v1",2)
	first=prepare_corpus(factory,manifest_path,TestEncoder(config),True)
	assert all(item["published"] for item in first)
	encoder=TestEncoder(config)
	second=prepare_corpus(factory,manifest_path,encoder,True)
	assert encoder.calls==0 and all(item["reused"] for item in second)
	assert [item["embedding_set_id"] for item in first]==[item["embedding_set_id"] for item in second]
	with pytest.raises(RuntimeError):
		prepare_corpus(factory,manifest_path,TestEncoder(replace(config,model="broken"),1),True)
	third=prepare_corpus(factory,manifest_path,TestEncoder(config),True)
	assert [item["embedding_set_id"] for item in third]==[item["embedding_set_id"] for item in first]
