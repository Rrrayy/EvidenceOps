import httpx
import json
import pytest

from evidenceops.application.context_assembler import ContextAssembler
from evidenceops.application.model_protocol import ModelRequest
from evidenceops.application.token_budget import ContextBudgetError,ContextConfig,HeuristicTokenEstimator,TokenLedger
from evidenceops.infrastructure.providers.openai_compatible_provider import OpenAICompatibleProvider
from dataclasses import replace
from datetime import datetime,timezone
from hashlib import sha256

from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.context_assembler import EvidenceProjection,to_projections
from evidenceops.application.knowledge_retrieval import KeywordKnowledgeRetriever
from evidenceops.application.llm_gateway import LLMGateway
from evidenceops.application.model_protocol import FinalAnswer,ToolCall
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.connectors.knowledge_search import build_knowledge_search_tool
from evidenceops.domain.evidence import Evidence,EvidenceSource
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from test_knowledge_evidence import corpus


def test_context_config_rejects_bool_and_window_overflow():
	with pytest.raises(ValueError): ContextConfig(context_window_tokens=True)
	with pytest.raises(ValueError): ContextConfig(context_window_tokens=100,max_output_tokens=80,safety_margin_tokens=21)


def test_assembler_reserves_and_deduplicates():
	config=ContextConfig(context_window_tokens=1000,max_output_tokens=100,safety_margin_tokens=10,max_run_tokens=1000)
	ledger=TokenLedger(config)
	result=ContextAssembler(config).assemble(({"role":"user","content":"故障"},),(),ledger,evidences=())
	assert result.estimated_input_tokens>0
	assert result.reservation.payload_hash
	assert ledger.used_tokens==result.reservation.reserved_tokens


def test_assembler_fails_before_provider_when_context_is_full():
	config=ContextConfig(context_window_tokens=30,max_output_tokens=10,safety_margin_tokens=5,max_run_tokens=100)
	with pytest.raises(ContextBudgetError) as error:
		ContextAssembler(config).assemble(({"role":"user","content":"这是一段足够长的中文故障描述，应该超过窗口"},),(),TokenLedger(config))
	assert error.value.error_code=="CONTEXT_BUDGET_EXCEEDED"


def test_incomplete_usage_keeps_full_reservation_conservative():
	config=ContextConfig(context_window_tokens=1000,max_output_tokens=100,safety_margin_tokens=10,max_run_tokens=1000)
	ledger=TokenLedger(config)
	reservation=ledger.reserve(50,{"messages":[]})
	ledger.settle(reservation,70,"partial")
	assert ledger.settled_tokens==reservation.reserved_tokens
	assert ledger.unknown_calls==1


def test_provider_sends_max_tokens_and_marks_invalid_usage():
	captured=[]
	def response(request):
		captured.append(json.loads(request.content))
		return httpx.Response(200,json={"model":"x","choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":"bad","completion_tokens":1,"total_tokens":2}})
	config=type("Config",(),{})()
	provider=OpenAICompatibleProvider("https://embedding.example", "key", client=httpx.Client(transport=httpx.MockTransport(response)))
	request=ModelRequest(({"role":"user","content":"x"},),(),"x",5,"req","run",max_output_tokens=12)
	result=provider.complete(request)
	assert captured[0]["max_tokens"]==12
	assert result.usage.status=="invalid"
	provider.close()


def projection_evidence(evidence_id,content="核对服务解释器",snapshot=True):
	return Evidence(evidence_id,"run-projection",EvidenceSource.KNOWLEDGE,datetime.now(timezone.utc),
		"排障摘要","knowledge:test",sha256(content.encode("utf-8")).hexdigest(),
		content_snapshot=content if snapshot else None)


def test_evidence_projection_dedup():
	first=projection_evidence("evidence-first")
	second=replace(first,evidence_id="evidence-second")
	projections=to_projections((first,second))
	# 转换阶段保留别名，避免去重后丢失审计所需的信息。
	assert len(projections)==2
	assert projections[0].identity==first.content_hash
	assert projections[0].role=="optional"
	config=ContextConfig()
	result=ContextAssembler(config).assemble(({"role":"user","content":"诊断"},),(),TokenLedger(config),projections)
	assert result.visible_evidence_ids==("evidence-first",)
	assert result.deduplication_map=={"evidence-second":"evidence-first"}
	assert result.omissions==({"evidence_id":"evidence-second","reason":"duplicate","canonical_id":"evidence-first"},)
	assert len(result.messages)==2
	assert json.loads(result.messages[-1]["content"])["evidence_id"]=="evidence-first"


def test_evidence_reaches_messages():
	evidences=(projection_evidence("first"),projection_evidence("second","检查锁定依赖"))
	config=ContextConfig()
	result=ContextAssembler(config).assemble(({"role":"user","content":"诊断"},),(),TokenLedger(config),to_projections(evidences))
	assert len(result.messages)==3
	assert result.visible_evidence_ids==("first","second")
	assert result.deduplication_map=={} and result.omissions==()
	for message,evidence in zip(result.messages[1:],evidences):
		assert message["role"]=="user"
		payload=json.loads(message["content"])
		assert payload["evidence_id"]==evidence.evidence_id
		assert payload["content"]==evidence.content_snapshot
		assert "不可信" in payload["notice"]


def test_evidence_projection_falls_back_to_summary():
	evidence=projection_evidence("summary-only",snapshot=False)
	assert to_projections((evidence,))[0].content==evidence.summary
	assert to_projections(())==()


@pytest.mark.parametrize("existing_content",["核对服务解释器","另一段正文"])
def test_existing_tool_message_requires_matching_id_and_content(existing_content):
	evidence=projection_evidence("first")
	history=({"role":"user","content":"诊断"},
		{"role":"assistant","tool_calls":[{"id":"call-one","type":"function","function":{"name":"search_knowledge","arguments":"{}"}}]},
		{"role":"tool","tool_call_id":"call-one","content":json.dumps({"matches":[{"evidence_id":"first","content":existing_content}]})})
	config=ContextConfig()
	result=ContextAssembler(config).assemble(history,(),TokenLedger(config),to_projections((evidence,)))
	assert result.messages[:3]==history
	assert len(result.messages)==(3 if existing_content==evidence.content_snapshot else 4)
	assert result.visible_evidence_ids==("first",)
	assert [message for message in result.messages if message["role"]=="tool"]==[history[-1]]


def test_agent_loop_passes_bound_evidence_to_context_assembler(monkeypatch):
	found=KeywordKnowledgeRetriever().search(corpus(),"线程池 重试",5)
	assert len(found)>=2
	tool=build_knowledge_search_tool(lambda query,**options:found)
	assemblies=[]
	original=ContextAssembler.assemble
	def capture(self,*args,**kwargs):
		assembly=original(self,*args,**kwargs)
		assemblies.append((kwargs["evidences"],assembly))
		return assembly
	monkeypatch.setattr(ContextAssembler,"assemble",capture)
	def final(request):
		assert [message["role"] for message in request.messages]==["user","assistant","tool"]
		assert request.messages[-1]["tool_call_id"]=="knowledge-one"
		fragments=json.loads(request.messages[-1]["content"])["data"]["matches"]
		assert len(fragments)==len(found)
		assert [fragment["content"] for fragment in fragments]==[match.chunk.content for match in found]
		return FinalAnswer("参考资料已收到")
	provider=MockProvider((ToolCall("knowledge-one","search_knowledge",{"query":"线程池 重试"}),final))
	runtime=ToolRuntime((tool,))
	try:
		result=AgentLoop(LLMGateway(provider,"mock"),runtime,(tool,),context_config=ContextConfig()).run("查询参考资料",run_id="run-projection")
		assert result.error_code is None
		assert assemblies[0][0]==() and assemblies[0][1].visible_evidence_ids==()
		bound=result.tool_results[0].bound_evidences
		assert assemblies[1][0]==to_projections(bound)
		assert assemblies[1][1].visible_evidence_ids==tuple(item.evidence_id for item in bound)
	finally:
		runtime.close()


def test_projection_budget_failure_still_stops_before_provider():
	config=ContextConfig(context_window_tokens=200,max_output_tokens=10,safety_margin_tokens=5,max_run_tokens=1000)
	with pytest.raises(ContextBudgetError) as error:
		ContextAssembler(config).assemble(({"role":"user","content":"诊断"},),(),TokenLedger(config),
			(EvidenceProjection("large","证据"*500),))
	assert error.value.error_code=="CONTEXT_BUDGET_EXCEEDED"


def test_duplicate_aliases_already_in_history_remain_visible():
	first=projection_evidence("first")
	second=replace(first,evidence_id="second")
	history=({"role":"user","content":"诊断"},
		{"role":"assistant","tool_calls":[{"id":"call-one","type":"function","function":{"name":"search_knowledge","arguments":"{}"}}]},
		{"role":"tool","tool_call_id":"call-one","content":json.dumps({"matches":[
			{"evidence_id":item.evidence_id,"content":item.content_snapshot} for item in (first,second)]})})
	config=ContextConfig()
	result=ContextAssembler(config).assemble(history,(),TokenLedger(config),to_projections((first,second)))
	assert result.messages==history
	assert result.visible_evidence_ids==("first","second")
	assert result.deduplication_map=={"second":"first"}
	assert result.omissions==()
