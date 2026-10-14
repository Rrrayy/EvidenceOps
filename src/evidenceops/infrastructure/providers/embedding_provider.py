"""独立Embedding Adapter；零自动重试，不持久化或记录API密钥。"""
from urllib.parse import urlsplit
import math
import httpx

from evidenceops.domain.knowledge_vectors import EncodingConfig,validate_vectors


class HttpEmbeddingProvider:
	def __init__(self,config:EncodingConfig,api_key:str,timeout:float=15,transport=None)->None:
		endpoint=urlsplit(config.deployment)
		if endpoint.scheme!="https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
			raise ValueError("Embedding部署必须是无凭据、无查询参数的HTTPS完整端点")
		if not api_key or not math.isfinite(timeout) or timeout<=0: raise ValueError("密钥或请求超时无效")
		self.config=config
		self._key=api_key
		self._timeout=timeout
		self._transport=transport

	def encode(self,texts:tuple[str,...],purpose:str,remaining:float):
		if remaining<=0: raise TimeoutError("Embedding预算耗尽")
		if purpose not in ("document","query"): raise ValueError("编码用途无效")
		mode=self.config.document_mode if purpose=="document" else self.config.query_mode
		# OpenAI兼容协议没有通用input_type；仅支持相同默认编码模式，其他模式交给专用Adapter。
		if mode!="default": raise ValueError("此Adapter仅支持default编码模式")
		with httpx.Client(transport=self._transport,follow_redirects=False,timeout=min(remaining,self._timeout)) as client:
			response=client.post(self.config.deployment,headers={"Authorization":"Bearer "+self._key},json={"model":self.config.model,"input":list(texts),"encoding_format":"float"})
			if response.status_code!=200: raise RuntimeError("Embedding HTTP失败: "+str(response.status_code))
			data=response.json()["data"]
		if not isinstance(data,list) or len(data)!=len(texts): raise ValueError("Embedding响应数量不匹配")
		ordered={}
		for item in data:
			index=item.get("index")
			if type(index) is not int or not 0<=index<len(texts) or index in ordered: raise ValueError("Embedding响应索引非法")
			ordered[index]=item["embedding"]
		return validate_vectors(tuple(ordered[index] for index in range(len(texts))),len(texts),self.config.dimensions)
