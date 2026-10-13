"""Embedding 抽象与确定性测试实现；真实供应商由后续 Adapter 注入。"""
from hashlib import sha256
import math
from typing import Protocol


class EmbeddingProvider(Protocol):
	def embed(self,texts:tuple[str,...])->tuple[tuple[float,...],...]: ...


class HashEmbeddingProvider:
	"""仅用于接口和回归测试，不代表语义向量质量。"""
	def __init__(self,dimensions:int=32)->None:
		if type(dimensions) is not int or dimensions<=0: raise ValueError("dimensions必须是正整数")
		self.dimensions=dimensions

	def embed(self,texts:tuple[str,...])->tuple[tuple[float,...],...]:
		if not isinstance(texts,tuple): raise TypeError("texts必须是元组")
		return tuple(self._one(text) for text in texts)

	def _one(self,text:str)->tuple[float,...]:
		if not isinstance(text,str) or not text.strip(): raise ValueError("文本不能为空")
		seed=sha256(text.encode("utf-8")).digest()
		values=tuple((seed[index%len(seed)]-127.5)/127.5 for index in range(self.dimensions))
		norm=math.sqrt(sum(value*value for value in values))
		return tuple(value/norm for value in values)


def cosine_similarity(left:tuple[float,...],right:tuple[float,...])->float:
	if len(left)!=len(right) or not left: raise ValueError("向量维度必须一致且非空")
	return sum(a*b for a,b in zip(left,right))
