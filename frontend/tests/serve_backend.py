import sys # 独立运行测试服务时定位源码。
from pathlib import Path # 路径不依赖调用终端。
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src")) # 只加载此仓库源码。
import json # 仅用于确定性的兼容模型响应。
import httpx # MockTransport 不请求真实供应商。
from evidenceops.api.model_connections import ConnectionManager # 浏览器验收真实管理 API。
from evidenceops.infrastructure.model_connections import ConnectionStore # 隔离配置持久化。
import sys # 显式测试端口参数。
import os # 测试配置与生产环境隔离。
import time # 用确定性等待留出取消和重连测试窗口。
from pathlib import Path # 测试数据库位于可删除的输出目录。
import uvicorn # 使用真实 ASGI 网络服务。
from sqlalchemy import create_engine # 独立 SQLite 仅用于联调测试。
from sqlalchemy.orm import sessionmaker # 为每次归档提供短事务。
from evidenceops.api.agent_app import build_final_answer # 复用产品 Mock 报告，不伪造前端报告。
from evidenceops.api.agent_diagnosis import create_app # 与生产前端共享完全相同 API。
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly # 复用实际 Agent 编排。
from evidenceops.application.model_protocol import ModelProviderError,ToolCall,ToolCallBatch,ProviderResponse # 测试供应商错误路径。
from evidenceops.connectors.local_log import build_local_log_tool # 使用真实只读日志工具。
from evidenceops.connectors.local_metric import build_local_metric_tool # 使用真实指标工具。
from evidenceops.connectors.local_config import build_local_config_tool # 使用真实配置工具。
from evidenceops.infrastructure.database.models import Base # 创建隔离测试表。
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence # 复用实际持久化事务。
from evidenceops.infrastructure.providers.mock_provider import MockProvider # 仅使用确定性模型，不产生供应商费用。


class BrowserTestProvider(MockProvider):
	# 测试专用慢模型，生产服务不包含这些触发词。
	def complete(self,request):
		text=next(message["content"] for message in request.messages if message["role"]=="user")
		for _ in range(10 if "取消" in text or "重连" in text else 2):
			time.sleep(0.12)
			if request.control:
				request.control.check()
		if "模型失败" in text:
			raise ModelProviderError("MODEL_TIMEOUT","测试模型请求超时")
		# 通过请求消息判定阶段，不在多个 Run 之间共享可变响应索引。
		observations=[message for message in request.messages if message["role"]=="tool"]
		return ProviderResponse(build_final_answer(request) if observations else ToolCallBatch(self._responses),request.model,None)


def model_response(request):
	# 测试专用供应商兼容响应；不在生产代码添加触发词。
	if request.headers.get("authorization")=="Bearer wrong-test-key": return httpx.Response(401,json={"error":"认证失败"})
	if request.method=="GET": return httpx.Response(200,json={"data":[{"id":"agent-model"},{"id":"long-agent-model-for-evidenceops-2026"}]})
	body=json.loads(request.content)
	if any(tool.get("function",{}).get("name")=="evidenceops_probe" for tool in body.get("tools",[])):
		message={"content":None,"tool_calls":[{"id":"probe-call","type":"function","function":{"name":"evidenceops_probe","arguments":"{}"}}]}
	elif any(message.get("tool_call_id")=="probe-call" for message in body["messages"]):
		message={"content":json.dumps({"root_cause":{"text":"evidenceops-validation-checked","evidence_ids":["validation-evidence"]},"recommendations":[{"text":"验证关联","evidence_ids":["validation-evidence"]}],"confidence":0.5,"limitations":"隔离验证"})}
	elif body["messages"][0].get("role")=="system":
		observations=[json.loads(message["content"]) for message in body["messages"] if message["role"]=="tool"]
		if observations:
			identities=[message["evidence_id"] for message in observations]
			message={"content":json.dumps({"root_cause":{"text":"隔离模型诊断结果","evidence_ids":identities},"recommendations":[{"text":"检查服务指标","evidence_ids":identities}],"confidence":0.5,"limitations":"隔离测试，不代表真实模型质量"})}
		else:
			message={"content":None,"tool_calls":[{"id":"business-log","type":"function","function":{"name":"query_service_logs","arguments":json.dumps({"service_name":"order-service","environment":"production","error_type":"rpc_timeout","start_time":"2026-10-05T10:00:00+08:00","end_time":"2026-10-05T10:10:00+08:00","limit":50})}}]}
	else: message={"content":"OK"}
	return httpx.Response(200,json={"model":body["model"],"choices":[{"message":message}]})


def build_test_app(diagnosis_persistence=None,connection_store=None):
	# 只在 output 内创建数据库，不读取用户 .env 或 PostgreSQL。
	os.environ["EVIDENCEOPS_MODEL_ALLOWED_HOSTS"]="maas.qianwenaiapi.com,dashscope.aliyuncs.com,models.example" # 仅隔离测试环境允许虚拟域名。
	output=Path(os.getenv("EVIDENCEOPS_BROWSER_TEST_ROOT","output/playwright"))
	output.mkdir(parents=True,exist_ok=True)
	if diagnosis_persistence is None:
		engine=create_engine(f"sqlite:///{output/'console-test.db'}",connect_args={"check_same_thread":False})
		Base.metadata.create_all(engine)
		diagnosis_persistence=SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)
	arguments={"service_name":"order-service","environment":"production","start_time":"2026-10-05T10:00:00+08:00","end_time":"2026-10-05T10:10:00+08:00","limit":50}
	provider=BrowserTestProvider((ToolCall("call-log-001","query_service_logs",{**arguments,"error_type":"rpc_timeout"}),ToolCall("call-metric-001","query_service_metrics",arguments),ToolCall("call-config-001","query_service_config",{"service_name":"order-service","environment":"production","at_time":"2026-10-05T10:02:00+08:00"})))
	assembly=build_agent_diagnosis_assembly(provider,"browser-test",(build_local_log_tool(),build_local_metric_tool(),build_local_config_tool()),"order-service",diagnosis_persistence=diagnosis_persistence,run_timeout_seconds=15)
	return create_app(assembly,ConnectionManager(assembly,connection_store or ConnectionStore(output/"model-connections"),lambda:httpx.Client(transport=httpx.MockTransport(model_response))))


if __name__=="__main__":
	# 显式独立端口，避免干扰现有后端。
	uvicorn.run(build_test_app(),host="127.0.0.1",port=int(sys.argv[1]) if len(sys.argv)>1 else int(os.getenv("EVIDENCEOPS_TEST_PORT","8011")))
