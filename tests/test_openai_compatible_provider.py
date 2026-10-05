import httpx
import pytest

from evidenceops.application.model_protocol import (
	FinalAnswer,
	ModelProviderError,
	ModelRequest,
	StructuredFinalAnswer,
	ToolCall,
	ToolCallBatch,
)
from evidenceops.infrastructure.providers.openai_compatible_provider import (
	OpenAICompatibleProvider,
)


class FakeResponse:
	def __init__(self,status_code:int,payload:object)->None:
		self.status_code=status_code
		self._payload=payload

	def json(self)->object:
		return self._payload


class InvalidJsonResponse:
	status_code=200

	def json(self)->object:
		raise ValueError("invalid json")


class FakeClient:
	def __init__(
		self,
		response:object=None,
		error:Exception|None=None,
	)->None:
		self._response=response
		self._error=error
		self.url=None
		self.headers=None
		self.body=None
		self.timeout=None

	def post(self,url,headers,json,timeout):
		self.url=url
		self.headers=headers
		self.body=json
		self.timeout=timeout

		if self._error is not None:
			raise self._error

		return self._response

	def close(self)->None:
		pass


def build_request(
	response_format:str="text",
)->ModelRequest:
	return ModelRequest(
		messages=(
			{
				"role":"user",
				"content":"分析 order-service 的 RPC 超时",
			},
		),
		tools=(
			{
				"type":"function",
				"function":{
					"name":"query_thread_pool_snapshot",
				},
			},
		),
		model="test-model",
		timeout_seconds=3.0,
		request_id="req-001",
		run_id="run-001",
		response_format=response_format,
	)


def build_provider(
	client:FakeClient,
)->OpenAICompatibleProvider:
	return OpenAICompatibleProvider(
		base_url="https://example.com/v1",
		api_key="test-key",
		client=client,
	)


def test_provider_parses_final_answer_and_usage()->None:
	client=FakeClient(
		FakeResponse(
			200,
			{
				"model":"test-model",
				"choices":[
					{
						"message":{
							"content":"线程池存在任务积压。",
						},
					},
				],
				"usage":{
					"prompt_tokens":10,
					"completion_tokens":8,
					"total_tokens":18,
				},
			},
		),
	)

	result=build_provider(client).complete(build_request())

	assert isinstance(result.response,FinalAnswer)
	assert result.response.text=="线程池存在任务积压。"
	assert result.model=="test-model"
	assert result.usage is not None
	assert result.usage.total_tokens==18


def test_provider_parses_tool_call_arguments()->None:
	client=FakeClient(
		FakeResponse(
			200,
			{
				"model":"test-model",
				"choices":[
					{
						"message":{
							"tool_calls":[
								{
									"id":"call-001",
									"function":{
										"name":"query_thread_pool_snapshot",
										"arguments":(
											"{\"service_name\":\"order-service\"}"
										),
									},
								},
							],
						},
					},
				],
			},
		),
	)

	result=build_provider(client).complete(build_request())

	assert isinstance(result.response,ToolCall)
	assert result.response.tool_call_id=="call-001"
	assert result.response.tool_name=="query_thread_pool_snapshot"
	assert result.response.arguments=={
		"service_name":"order-service",
	}
	assert result.usage is None


def test_provider_builds_http_request()->None:
	client=FakeClient(
		FakeResponse(
			200,
			{
				"choices":[
					{
						"message":{
							"content":"完成",
						},
					},
				],
			},
		),
	)

	build_provider(client).complete(build_request())

	assert client.url=="https://example.com/v1/chat/completions"
	assert client.headers["Authorization"]=="Bearer test-key"
	assert client.headers["X-Request-ID"]=="req-001"
	assert client.headers["X-Run-ID"]=="run-001"
	assert client.body["model"]=="test-model"
	assert client.body["messages"][0]["role"]=="user"
	assert client.timeout==3.0


def test_provider_converts_timeout()->None:
	client=FakeClient(error=httpx.TimeoutException("timeout"))

	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(build_request())

	assert error_info.value.error_code=="MODEL_TIMEOUT"


def test_provider_converts_network_error()->None:
	client=FakeClient(
		error=httpx.ConnectError("connection failed"),
	)

	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(build_request())

	assert error_info.value.error_code=="MODEL_NETWORK_ERROR"


@pytest.mark.parametrize(
	("status_code","error_code"),
	(
		(401,"MODEL_AUTH_FAILED"),
		(403,"MODEL_AUTH_FAILED"),
		(429,"MODEL_RATE_LIMITED"),
		(500,"MODEL_SERVER_ERROR"),
		(400,"MODEL_HTTP_ERROR"),
	),
)
def test_provider_converts_http_error(
	status_code:int,
	error_code:str,
)->None:
	client=FakeClient(
		FakeResponse(status_code,{})
	)

	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(build_request())

	assert error_info.value.error_code==error_code


def test_provider_rejects_invalid_json()->None:
	client=FakeClient(InvalidJsonResponse())

	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(build_request())

	assert error_info.value.error_code=="MODEL_PROTOCOL_ERROR"


def test_provider_rejects_empty_choices()->None:
	client=FakeClient(
		FakeResponse(
			200,
			{
				"choices":[],
			},
		),
	)

	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(build_request())

	assert error_info.value.error_code=="MODEL_PROTOCOL_ERROR"


def test_provider_rejects_invalid_tool_arguments()->None:
	client=FakeClient(
		FakeResponse(
			200,
			{
				"choices":[
					{
						"message":{
							"tool_calls":[
								{
									"id":"call-001",
									"function":{
										"name":"query_thread_pool_snapshot",
										"arguments":"not-json",
									},
								},
							],
						},
					},
				],
			},
		),
	)

	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(build_request())

	assert error_info.value.error_code=="MODEL_PROTOCOL_ERROR"

def test_provider_parses_multiple_tool_calls()->None:
	calls=[{
		"id":f"call-{index}",
		"function":{"name":"query","arguments":f'{{"value":{index}}}'},
	} for index in range(3)]
	client=FakeClient(FakeResponse(200,{"choices":[{"message":{"tool_calls":calls}}]}))
	result=build_provider(client).complete(build_request())
	assert isinstance(result.response,ToolCallBatch)
	assert [call.arguments for call in result.response.calls]==[{"value":index} for index in range(3)]
	assert [call.tool_call_id for call in result.response.calls]==[f"call-{index}" for index in range(3)]


@pytest.mark.parametrize("fault",["duplicate_id","invalid_second_arguments","too_many"])
def test_provider_rejects_invalid_batch_before_execution(fault)->None:
	calls=[{"id":f"call-{index}","function":{"name":"query","arguments":"{}"}} for index in range(2)]
	if fault=="duplicate_id":
		calls[1]["id"]=calls[0]["id"]
	elif fault=="invalid_second_arguments":
		calls[1]["function"]["arguments"]="not-json"
	else:
		calls=[{"id":str(index),"function":{"name":"query","arguments":"{}"}} for index in range(17)]
	client=FakeClient(FakeResponse(200,{"choices":[{"message":{"tool_calls":calls}}]}))
	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(build_request())
	assert error_info.value.error_code=="MODEL_PROTOCOL_ERROR"


def test_provider_parses_structured_final_answer()->None:
	client=FakeClient(
		FakeResponse(
			200,
			{
				"model":"test-model",
				"choices":[
					{
						"message":{
							"content":(
								"{"
								"\"root_cause\":{"
								"\"text\":\"线程池耗尽导致RPC请求排队\","
								"\"evidence_ids\":[\"run-001-thread-pool\"]"
								"},"
								"\"recommendations\":["
								"{"
								"\"text\":\"扩大线程池容量\","
								"\"evidence_ids\":[\"run-001-thread-pool\"]"
								"}"
								"],"
								"\"confidence\":0.91,"
								"\"limitations\":\"当前只检查了线程池指标\""
								"}"
							),
						},
					},
				],
			},
		),
	)

	result=build_provider(client).complete(
		build_request("json_object")
	)

	assert isinstance(result.response,StructuredFinalAnswer)
	assert result.response.data["confidence"]==0.91
	assert result.response.data["root_cause"]["evidence_ids"]==[
		"run-001-thread-pool",
	]
	assert client.body["response_format"]=={
		"type":"json_object",
	}


def test_provider_rejects_invalid_structured_content()->None:
	client=FakeClient(
		FakeResponse(
			200,
			{
				"choices":[
					{
						"message":{
							"content":"线程池存在任务积压",
						},
					},
				],
			},
		),
	)

	with pytest.raises(ModelProviderError) as error_info:
		build_provider(client).complete(
			build_request("json_object")
		)

	assert error_info.value.error_code=="MODEL_PROTOCOL_ERROR"
