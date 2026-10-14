"""编码空间快照：配置相同是兼容的必要条件，不保证供应商没有静默升级。"""
from dataclasses import asdict,dataclass
from hashlib import sha256
import json
import math


@dataclass(frozen=True,slots=True)
class EncodingConfig:
	provider:str
	deployment:str
	model:str
	dimensions:int
	revision:str="unknown"
	document_mode:str="document"
	query_mode:str="query"
	document_prefix:str=""
	query_prefix:str=""
	preprocessing:str="identity-v1"
	truncation:str="reject"
	normalization:str="l2"
	max_characters:int=8000

	def __post_init__(self)->None:
		for value in (self.provider,self.deployment,self.model,self.revision,self.document_mode,self.query_mode):
			if not isinstance(value,str) or not value.strip(): raise ValueError("编码配置身份不能为空")
		if type(self.dimensions) is not int or not 1<=self.dimensions<=8192: raise ValueError("dimensions必须在1到8192之间")
		if type(self.max_characters) is not int or not 1<=self.max_characters<=100000: raise ValueError("max_characters无效")
		if not isinstance(self.document_prefix,str) or not isinstance(self.query_prefix,str): raise ValueError("prefix必须是文本")
		if self.preprocessing!="identity-v1" or self.truncation!="reject" or self.normalization!="l2":
			raise ValueError("本批仅支持原文保留、超长拒绝和L2归一化")

	@property
	def fingerprint(self)->str:
		return sha256(json.dumps(asdict(self),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()

	def prepare(self,texts:tuple[str,...],purpose:str)->tuple[str,...]:
		if purpose not in ("document","query"): raise ValueError("purpose无效")
		prefix=self.document_prefix if purpose=="document" else self.query_prefix
		if not texts or any(not isinstance(text,str) or not text.strip() for text in texts): raise ValueError("编码正文不能为空")
		prepared=tuple(prefix+text for text in texts)
		if any(len(text)>self.max_characters for text in prepared): raise ValueError("编码正文超过字符上限；不会静默截断")
		return prepared


def validate_vectors(vectors,expected_count:int,dimensions:int)->tuple[tuple[float,...],...]:
	"""每批校验并归一化；按最大绝对值缩放，避免有限大数平方溢出。"""
	if len(vectors)!=expected_count: raise ValueError("Embedding响应数量不匹配")
	validated=[]
	for vector in vectors:
		if len(vector)!=dimensions: raise ValueError("Embedding维度不匹配")
		if any(type(value) not in (int,float) or not math.isfinite(value) for value in vector):
			raise ValueError("Embedding包含非法或非有限数字")
		scale=max(abs(value) for value in vector)
		if scale==0: raise ValueError("Embedding不能是零向量")
		scaled=tuple(value/scale for value in vector)
		norm=math.hypot(*scaled)
		validated.append(tuple(value/norm for value in scaled))
	return tuple(validated)
