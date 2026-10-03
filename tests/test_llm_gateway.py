import pytest

from evidenceops.application.llm_gateway import LLMGateway,ModelGatewayError
from evidenceops.application.model_protocol import (
	FinalAnswer,
	ModelRequest,
	ProviderResponse,
)


def build_request()->ModelRequest:
	return ModelRequest(
		messages=(),
		tools=(),
		model="mock-model",
		timeout_seconds=1.0,
		request_id="req-001",
		run_id="run-001",
	)


class SuccessfulProvider:
	def complete(self,request:ModelRequest)->ProviderResponse:
		return ProviderResponse(
			response=FinalAnswer("诊断完成"),
			model=request.model,
			usage=None,
		)


class TimeoutProvider:
	def complete(self,request:ModelRequest)->ProviderResponse:
		raise TimeoutError("provider timeout")


def test_gateway_wraps_provider_response()->None:
	result=LLMGateway(SuccessfulProvider(),"mock").complete(build_request())

	assert result.response.text=="诊断完成"
	assert result.provider=="mock"
	assert result.model=="mock-model"
	assert result.latency_ms>=0
	assert result.request_id=="req-001"


def test_gateway_converts_timeout()->None:
	with pytest.raises(ModelGatewayError,match="模型请求超时") as error_info:
		LLMGateway(TimeoutProvider(),"mock").complete(build_request())

	assert error_info.value.error_code=="MODEL_TIMEOUT"
