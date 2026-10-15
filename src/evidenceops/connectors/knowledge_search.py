"""只读文档清单检索工具：不接收路径、密钥或任意集合选择。"""
import math

from evidenceops.application.knowledge_evidence import matches_to_evidence
from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.application.run_control import RunCancelled
from evidenceops.application.run_budget import RunBudgetExceeded
from evidenceops.application.tool_runtime import ToolSpec


def build_knowledge_search_tool(search,budget:float=8)->ToolSpec:
	if not math.isfinite(budget) or budget<=0: raise ValueError("检索预算无效")
	def validate(arguments):
		if set(arguments)-{"query","top_k"}: raise ValueError("知识查询仅接受query和top_k")
		query=arguments.get("query")
		top_k=arguments.get("top_k",3)
		if not isinstance(query,str) or not query.strip() or len(query)>2000: raise ValueError("query必须为1到2000字符的非空文本")
		if type(top_k) is not int or not 1<=top_k<=5: raise ValueError("top_k必须在1到5之间")
		return {"query":query,"top_k":top_k}
	def invoke(arguments,control=None):
		try:
			if control is not None: control.check()
			matches=search(arguments["query"],top_k=arguments["top_k"],budget=budget)
			if control is not None: control.check()
			if not isinstance(matches,tuple) or len(matches)>arguments["top_k"] or any(not isinstance(match,KnowledgeMatch) for match in matches):
				raise ValueError("知识检索返回类型或数量无效")
			if sum(len(match.chunk.content) for match in matches)>16000: raise ValueError("知识上下文超过16000字符预算")
			# 在Runtime宣布工具成功之前校验快照，避免模型看到无法归档的正文。
			matches_to_evidence("validation","validation",matches)
			return matches
		except (RunCancelled,RunBudgetExceeded):
			raise
		except TimeoutError as error:
			raise TimeoutError("知识检索超时") from error
		except Exception as error:
			# 不向模型、SSE或历史响应暴露供应商响应、连接串和密钥。
			raise RuntimeError("知识检索失败，请检查集合和Embedding服务") from error
	return ToolSpec("search_knowledge",True,validate,invoke,{
		"type":"object","properties":{
			"query":{"type":"string","minLength":1,"maxLength":2000,"description":"检索排障方法；资料不能证明本次故障根因"},
			"top_k":{"type":"integer","minimum":1,"maximum":5,"default":3}},
		"required":["query"],"additionalProperties":False},controlled_handler=invoke,timeout_seconds=budget)
