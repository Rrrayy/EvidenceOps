import pytest

from evidenceops.application.model_protocol import (
	FinalAnswer,
	ModelRequest,
	ModelUsage,
	ToolCall,
)


def test_tool_call_keeps_tool_call_id()->None:
	tool_call=ToolCall(
		"call-001",
		"query_thread_pool_snapshot",
		{"service_name":"order-service"},
	)

	assert tool_call.tool_call_id=="call-001"
	assert tool_call.tool_name=="query_thread_pool_snapshot"


def test_model_request_rejects_non_positive_timeout()->None:
	with pytest.raises(ValueError,match="timeout_seconds必须大于0"):
		ModelRequest((),(),"mock-model",0,"req-001","run-001")


def test_model_usage_rejects_negative_tokens()->None:
	with pytest.raises(ValueError,match="Token数量不能为负数"):
		ModelUsage(-1,None,None)


def test_final_answer_rejects_blank_text()->None:
	with pytest.raises(ValueError,match="最终答案不能为空"):
		FinalAnswer("   ")
