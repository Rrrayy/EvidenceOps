import time

from evidenceops.application.model_protocol import (
	ModelCallResult,
	ModelProvider,
	ModelRequest,
)


class ModelGatewayError(RuntimeError):
	def __init__(self,error_code:str,error_message:str)->None:
		super().__init__(error_message)
		self.error_code=error_code
		self.error_message=error_message


class LLMGateway:
	def __init__(self,provider:ModelProvider,provider_name:str)->None:
		if not isinstance(provider_name,str) or not provider_name.strip():
			raise ValueError("provider_name不能为空")

		self._provider=provider
		self._provider_name=provider_name

	def complete(self,request:ModelRequest)->ModelCallResult:
		start_time=time.perf_counter()

		try:
			provider_response=self._provider.complete(request)
		except TimeoutError as error:
			raise ModelGatewayError(
				"MODEL_TIMEOUT",
				"模型请求超时",
			) from error
		except ConnectionError as error:
			raise ModelGatewayError(
				"MODEL_NETWORK_ERROR",
				"模型网络请求失败",
			) from error
		except Exception as error:
			raise ModelGatewayError(
				"MODEL_EXECUTION_FAILED",
				"模型调用失败",
			) from error

		latency_ms=(time.perf_counter()-start_time)*1000

		return ModelCallResult(
			response=provider_response.response,
			provider=self._provider_name,
			model=provider_response.model,
			latency_ms=latency_ms,
			usage=provider_response.usage,
			request_id=request.request_id,
		)