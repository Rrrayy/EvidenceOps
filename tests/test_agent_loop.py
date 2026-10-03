from evidenceops.application.agent_loop import AgentLoop
from evidenceops.application.llm_gateway import LLMGateway
from evidenceops.application.model_protocol import FinalAnswer,ToolCall
from evidenceops.application.tool_runtime import ToolRuntime
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.mocks.thread_pool import build_thread_pool_tool


def build_runtime()->ToolRuntime:
	return ToolRuntime((build_thread_pool_tool(),),timeout_seconds=1.0)


def build_loop(
	responses:tuple,
	max_steps:int=3,
)->tuple[AgentLoop,ToolRuntime]:
	runtime=build_runtime()
	provider=MockProvider(responses)
	gateway=LLMGateway(provider,"mock")
	loop=AgentLoop(gateway,runtime,max_steps=max_steps)
	return loop,runtime


def test_agent_loop_calls_tool_then_returns_final_answer()->None:
	loop,runtime=build_loop((
		ToolCall(
			"call-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		FinalAnswer("线程池满载并存在任务积压"),
	))

	try:
		result=loop.run("分析订单服务RPC超时",run_id="run-001")
	finally:
		runtime.close()

	assert result.error_code is None
	assert result.final_answer=="线程池满载并存在任务积压"
	assert len(result.tool_results)==1
	assert result.tool_results[0].ok is True
	assert result.tool_results[0].tool_call_id=="call-001"


def test_agent_loop_returns_tool_failure()->None:
	loop,runtime=build_loop((
		ToolCall(
			"call-001",
			"query_thread_pool_snapshot",
			{"service_name":"payment-service"},
		),
	))

	try:
		result=loop.run("分析支付服务RPC超时",run_id="run-002")
	finally:
		runtime.close()

	assert result.final_answer is None
	assert result.error_code=="TOOL_EXECUTION_FAILED"
	assert len(result.tool_results)==1
	assert result.tool_results[0].tool_call_id=="call-001"


def test_agent_loop_stops_after_max_steps()->None:
	loop,runtime=build_loop((
		ToolCall(
			"call-001",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
		ToolCall(
			"call-002",
			"query_thread_pool_snapshot",
			{"service_name":"order-service"},
		),
	),max_steps=2)

	try:
		result=loop.run("持续分析订单服务",run_id="run-003")
	finally:
		runtime.close()

	assert result.final_answer is None
	assert result.error_code=="AGENT_MAX_STEPS"
	assert len(result.tool_results)==2


def test_tool_call_rejects_empty_tool_call_id()->None:
	try:
		ToolCall("","query_thread_pool_snapshot",{})
	except ValueError as error:
		assert str(error)=="tool_call_id不能为空"
	else:
		raise AssertionError("缺少tool_call_id时应该失败")
