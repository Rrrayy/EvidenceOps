import json
from typing import Any
from urllib.parse import urlparse

import httpx

from evidenceops.application.model_protocol import (
	FinalAnswer,
	ModelProviderError,
	ModelRequest,
	ModelUsage,
	ProviderResponse,
	StructuredFinalAnswer,
	ToolCall,
	ToolCallBatch,
)


class OpenAICompatibleProvider:
	def __init__(
		self,
		base_url:str,
		api_key:str,
		client:httpx.Client|None=None,
	)->None:
		if not isinstance(base_url,str) or not base_url.strip():
			raise ValueError("base_url不能为空")

		if not isinstance(api_key,str) or not api_key.strip():
			raise ValueError("api_key不能为空")

		normalized_base_url=base_url.strip()
		parsed_url=urlparse(normalized_base_url)

		if parsed_url.scheme not in ("http","https"):
			raise ValueError("base_url必须使用http或https协议")

		if not parsed_url.netloc:
			raise ValueError("base_url必须包含有效主机地址")

		self._url=f"{normalized_base_url.rstrip('/')}/chat/completions"
		self._api_key=api_key.strip()
		self._client=client or httpx.Client()

	def complete(self,request:ModelRequest)->ProviderResponse:
		headers={
			"Authorization":f"Bearer {self._api_key}",
			"Content-Type":"application/json",
			"X-Request-ID":request.request_id,
			"X-Run-ID":request.run_id,
		}

		body={
			"model":request.model,
			"messages":list(request.messages),
			"tools":list(request.tools),
		}

		if request.response_format=="json_object":
			body["response_format"]={"type":"json_object"}

		try:
			response=self._client.post(
				self._url,
				headers=headers,
				json=body,
				timeout=request.timeout_seconds,
			)
		except httpx.TimeoutException as error:
			raise ModelProviderError(
				"MODEL_TIMEOUT",
				"模型请求超时",
			) from error
		except httpx.RequestError as error:
			raise ModelProviderError(
				"MODEL_NETWORK_ERROR",
				"模型网络请求失败",
			) from error
		except httpx.HTTPError as error:
			raise ModelProviderError(
				"MODEL_HTTP_ERROR",
				"模型HTTP请求失败",
			) from error

		if response.status_code in (401,403):
			raise ModelProviderError(
				"MODEL_AUTH_FAILED",
				"模型认证失败",
			)

		if response.status_code==429:
			raise ModelProviderError(
				"MODEL_RATE_LIMITED",
				"模型请求触发限流",
			)

		if response.status_code>=500:
			raise ModelProviderError(
				"MODEL_SERVER_ERROR",
				OpenAICompatibleProvider._build_http_error_message(response),
			)

		if response.status_code>=400:
			raise ModelProviderError(
				"MODEL_HTTP_ERROR",
				OpenAICompatibleProvider._build_http_error_message(response),
			)

		try:
			payload=response.json()
		except ValueError as error:
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型响应不是合法JSON",
			) from error

		return self._parse_response(payload,request)

	@staticmethod
	def _build_http_error_message(response:httpx.Response)->str:
		message=f"模型请求失败，HTTP状态码：{response.status_code}"
		response_text=getattr(response,"text","").strip()

		if response_text:
			message=f"{message}，响应：{response_text[:500]}"

		return message

	def close(self)->None:
		self._client.close()

	@staticmethod
	def _parse_response(
		payload:dict[str,Any],
		request:ModelRequest,
	)->ProviderResponse:
		if not isinstance(payload,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型响应必须是JSON对象",
			)

		choices=payload.get("choices")

		if not isinstance(choices,list) or not choices:
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型响应缺少有效choices",
			)

		first_choice=choices[0]

		if not isinstance(first_choice,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型响应中的choice格式错误",
			)

		message=first_choice.get("message")

		if not isinstance(message,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型响应缺少有效message",
			)

		tool_calls=message.get("tool_calls")

		if tool_calls is not None:
			return OpenAICompatibleProvider._parse_tool_call(
				tool_calls,
				payload,
				request,
			)

		content=message.get("content")

		if not isinstance(content,str) or not content.strip():
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型响应既没有工具调用也没有最终答案",
			)

		if request.response_format=="json_object":
			return OpenAICompatibleProvider._parse_structured_answer(
				content,
				payload,
				request,
			)

		return ProviderResponse(
			response=FinalAnswer(content),
			model=OpenAICompatibleProvider._parse_model(
				payload,
				request.model,
			),
			usage=OpenAICompatibleProvider._parse_usage(payload),
		)

	@staticmethod
	def _parse_structured_answer(
		content:str,
		payload:dict[str,Any],
		request:ModelRequest,
	)->ProviderResponse:
		try:
			data=json.loads(content)
		except json.JSONDecodeError as error:
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型结构化输出不是合法JSON",
			) from error

		if not isinstance(data,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"模型结构化输出必须是JSON对象",
			)

		return ProviderResponse(
			response=StructuredFinalAnswer(data),
			model=OpenAICompatibleProvider._parse_model(
				payload,
				request.model,
			),
			usage=OpenAICompatibleProvider._parse_usage(payload),
		)

	@staticmethod
	def _parse_tool_call(
		tool_calls:Any,
		payload:dict[str,Any],
		request:ModelRequest,
	)->ProviderResponse:
		if not isinstance(tool_calls,list) or not 1<=len(tool_calls)<=16:
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"每轮工具调用必须包含1至16项",
			)

		calls=tuple(OpenAICompatibleProvider._parse_single_tool_call(item) for item in tool_calls)
		try:
			batch=ToolCallBatch(calls)
		except (ValueError,TypeError) as error:
			raise ModelProviderError("MODEL_PROTOCOL_ERROR",str(error)) from error
		return ProviderResponse(
			response=calls[0] if len(calls)==1 else batch,
			model=OpenAICompatibleProvider._parse_model(payload,request.model),
			usage=OpenAICompatibleProvider._parse_usage(payload),
		)

	@staticmethod
	def _parse_single_tool_call(tool_call:Any)->ToolCall:

		if not isinstance(tool_call,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"工具调用格式错误",
			)

		tool_call_id=tool_call.get("id")
		function=tool_call.get("function")

		if not isinstance(tool_call_id,str) or not tool_call_id.strip():
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"工具调用缺少有效ID",
			)

		if not isinstance(function,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"工具调用缺少function",
			)

		tool_name=function.get("name")
		raw_arguments=function.get("arguments")

		if not isinstance(tool_name,str) or not tool_name.strip():
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"工具调用缺少有效名称",
			)

		arguments=OpenAICompatibleProvider._parse_arguments(raw_arguments)

		return ToolCall(tool_call_id,tool_name,arguments)

	@staticmethod
	def _parse_arguments(raw_arguments:Any)->dict[str,Any]:
		if isinstance(raw_arguments,dict):
			return raw_arguments

		if not isinstance(raw_arguments,str):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"工具参数必须是JSON对象或JSON字符串",
			)

		try:
			arguments=json.loads(raw_arguments)
		except json.JSONDecodeError as error:
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"工具参数不是合法JSON",
			) from error

		if not isinstance(arguments,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"工具参数解析结果必须是JSON对象",
			)

		return arguments

	@staticmethod
	def _parse_model(
		payload:dict[str,Any],
		requested_model:str,
	)->str:
		model=payload.get("model")

		if isinstance(model,str) and model.strip():
			return model

		return requested_model

	@staticmethod
	def _parse_usage(payload:dict[str,Any])->ModelUsage|None:
		raw_usage=payload.get("usage")

		if raw_usage is None:
			return None

		if not isinstance(raw_usage,dict):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"usage格式错误",
			)

		values=(
			raw_usage.get("prompt_tokens"),
			raw_usage.get("completion_tokens"),
			raw_usage.get("total_tokens"),
		)

		if any(
			value is not None and (
				not isinstance(value,int) or value<0
			)
			for value in values
		):
			raise ModelProviderError(
				"MODEL_PROTOCOL_ERROR",
				"usage中的Token数量格式错误",
			)

		return ModelUsage(
			prompt_tokens=values[0],
			completion_tokens=values[1],
			total_tokens=values[2],
		)
