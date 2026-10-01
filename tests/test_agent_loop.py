import pytest

from evidenceops.application.agent_loop import FinalAnswer,ToolCall
from evidenceops.application.agent_loop import AgentLoop,FinalAnswer,ToolCall
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.mocks.mock_agent_model import ScriptedAgentModel
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def build_runtime()->ToolRuntime:
	return ToolRuntime((build_thread_pool_tool(),),timeout_seconds=1.0)


def test_agent_loop_calls_tool_then_returns_final_answer()->None:
	runtime=build_runtime()

	model=ScriptedAgentModel((
		ToolCall(
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		FinalAnswer("线程池满载并存在任务积压"),
	))

	loop=AgentLoop(model,runtime)

	try:
		result=loop.run("分析订单服务RPC超时")
	finally:
		runtime.close()

	assert result.error_code is None
	assert result.final_answer=="线程池满载并存在任务积压"
	assert len(result.tool_results)==1
	assert result.tool_results[0].ok is True


def test_agent_loop_returns_tool_failure()->None:
	runtime=build_runtime()

	model=ScriptedAgentModel((
		ToolCall(
			"query_thread_pool_snapshot",
			{"service_name":"payment-service"},
		),
	))

	loop=AgentLoop(model,runtime)

	try:
		result=loop.run("分析支付服务RPC超时")
	finally:
		runtime.close()

	assert result.final_answer is None
	assert result.error_code=="TOOL_EXECUTION_FAILED"
	assert len(result.tool_results)==1
	assert result.tool_results[0].ok is False


def test_agent_loop_stops_after_max_steps()->None:
	runtime=build_runtime()

	model=ScriptedAgentModel((
		ToolCall(
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		ToolCall(
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
	))

	loop=AgentLoop(model,runtime,max_steps=2)

	try:
		result=loop.run("持续分析订单服务")
	finally:
		runtime.close()

	assert result.final_answer is None
	assert result.error_code=="AGENT_MAX_STEPS"
	assert len(result.tool_results)==2

def test_tool_call_rejects_empty_tool_name()->None:
	with pytest.raises(ValueError,match="tool_name不能为空"):
		ToolCall("",{})


def test_tool_call_rejects_non_dict_arguments()->None:
	with pytest.raises(TypeError,match="arguments必须是字典"):
		ToolCall("query_thread_pool_snapshot",[])


def test_final_answer_rejects_empty_text()->None:
	with pytest.raises(ValueError,match="最终答案不能为空"):
		FinalAnswer("")