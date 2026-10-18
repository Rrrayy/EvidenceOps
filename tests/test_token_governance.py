import httpx
import json
import pytest

from evidenceops.application.context_assembler import ContextAssembler
from evidenceops.application.model_protocol import ModelRequest
from evidenceops.application.token_budget import ContextBudgetError,ContextConfig,HeuristicTokenEstimator,TokenLedger
from evidenceops.infrastructure.providers.openai_compatible_provider import OpenAICompatibleProvider


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
