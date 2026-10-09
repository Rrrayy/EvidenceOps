import pytest
from evidenceops.application.tool_runtime import ToolResult,ToolRuntime,ToolSpec
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def build_runtime()->ToolRuntime:
	return ToolRuntime((build_thread_pool_tool(),))


def test_runtime_executes_read_only_tool()->None:
	runtime=build_runtime()

	result=runtime.execute("query_thread_pool_snapshot",{"service_name":"order-service"})

	assert result.ok is True
	assert result.error_code is None
	assert result.data["active_threads"]==64
	assert result.data["thread_limit"]==64
	assert result.data["pending_tasks"]==12


def test_runtime_preserves_tool_call_id()->None:
	runtime=build_runtime()

	result=runtime.execute("query_thread_pool_snapshot",{"service_name":"order-service"},tool_call_id="call-001")

	assert result.ok is True
	assert result.tool_call_id=="call-001"


def test_runtime_rejects_unknown_tool()->None:
	runtime=build_runtime()

	result=runtime.execute("unknown_tool",{})

	assert result.ok is False
	assert result.error_code=="UNKNOWN_TOOL"
	assert result.data is None


def test_runtime_rejects_invalid_arguments()->None:
	runtime=build_runtime()

	result=runtime.execute("query_thread_pool_snapshot",{"service_name":""})

	assert result.ok is False
	assert result.error_code=="INVALID_ARGUMENTS"


def test_runtime_converts_handler_failure()->None:
	runtime=build_runtime()

	result=runtime.execute("query_thread_pool_snapshot",{"service_name":"payment-service"})

	assert result.ok is False
	assert result.error_code=="TOOL_EXECUTION_FAILED"


def test_runtime_rejects_non_read_only_tool()->None:
	dangerous_tool=ToolSpec(
		name="restart_service",
		read_only=False,
		validate_arguments=lambda arguments:arguments,
		handler=lambda arguments:{"restarted":True},
	)

	runtime=ToolRuntime((dangerous_tool,))

	result=runtime.execute("restart_service",{})

	assert result.ok is False
	assert result.error_code=="TOOL_POLICY_DENIED"


def test_tool_result_accepts_evidence_id()->None:
	result=ToolResult(
		tool_name="test-tool",
		ok=True,
		data={"value":1},
		tool_call_id="call-001",
		evidence_id="run-001-call-001",
	)

	assert result.evidence_id=="run-001-call-001"


def test_tool_result_rejects_blank_evidence_id()->None:
	with pytest.raises(ValueError):
		ToolResult(tool_name="test-tool",ok=True,data={"value":1},evidence_id="   ")
