from typing import Any

from evidenceops.application.agent_loop import ModelResponse


class ScriptedAgentModel:
	def __init__(self,responses:tuple[ModelResponse,...])->None:
		self._responses=responses
		self._index=0

	def respond(self,history:tuple[dict[str,Any],...])->ModelResponse:
		if self._index>=len(self._responses):
			raise RuntimeError("Mock模型没有更多响应")

		response=self._responses[self._index]
		self._index+=1
		return response