from evidenceops.application.model_protocol import ModelRequest,ProviderResponse # 与模型网关共享正式协议。
from evidenceops.infrastructure.providers.mock_provider import MockProvider # 复用确定性响应转换。


class DiagnosisMockProvider(MockProvider):
	# Web 演示按请求历史选择阶段，不能让多个 Run 消耗同一个全局索引。
	def complete(self,request:ModelRequest)->ProviderResponse:
		index=sum(message.get("role")=="tool" for message in request.messages)
		if index>=len(self._responses):
			raise RuntimeError("Mock诊断阶段超出响应范围")
		# 临时供应商仅执行当前阶段，既不修改共享状态也不泄漏其他 Run。
		return MockProvider(self._responses[index:]).complete(request)
