from collections.abc import Callable

from evidenceops.application.model_protocol import (
	ModelProvider,
	ModelRequest,
	ModelResponse,
	ModelUsage,
	ProviderResponse,
)


MockResponse=ModelResponse|Callable[[ModelRequest],ModelResponse]


class MockProvider:
	def __init__(self,responses:tuple[MockResponse,...])->None:
		if not responses:
			raise ValueError("responses不能为空")

		self._responses=responses
		self._index=0

	def complete(self,request:ModelRequest)->ProviderResponse:
		if self._index>=len(self._responses):
			raise RuntimeError("MockProvider没有更多响应")

		response_source=self._responses[self._index]
		self._index+=1

		response=(
			response_source(request)
			if callable(response_source)
			else response_source
		)

		return ProviderResponse(
			response=response,
			model=request.model,
			usage=None,
		)