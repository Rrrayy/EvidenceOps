import pytest

from evidenceops.application.model_protocol import (
	FinalAnswer,
	ModelRequest,
	ToolCall,
)
from evidenceops.infrastructure.providers.mock_provider import MockProvider


def build_request()->ModelRequest:
	return ModelRequest(
		messages=(),
		tools=(),
		model="mock-model",
		timeout_seconds=1.0,
		request_id="req-001",
		run_id="run-001",
	)


def test_mock_provider_returns_scripted_responses()->None:
	provider=MockProvider((
		ToolCall(
			"call-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		FinalAnswer("诊断完成"),
	))

	first=provider.complete(build_request())
	second=provider.complete(build_request())

	assert first.response.tool_call_id=="call-001"
	assert second.response.text=="诊断完成"


def test_mock_provider_fails_when_responses_are_exhausted()->None:
	provider=MockProvider((FinalAnswer("诊断完成"),))
	provider.complete(build_request())

	with pytest.raises(RuntimeError,match="没有更多响应"):
		provider.complete(build_request())
