"""模型上下文估算、单次预算和 Run 累计 Token 账本。"""
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any


class ContextBudgetError(RuntimeError):
	def __init__(self,code:str,message:str,details:dict|None=None)->None:
		super().__init__(message)
		self.error_code=code
		self.details=details or {}


@dataclass(frozen=True,slots=True)
class ContextConfig:
	context_window_tokens:int=32768
	max_output_tokens:int=2048
	safety_margin_tokens:int=256
	max_run_tokens:int=16384
	estimator_id:str="heuristic-json-v1"
	limits_source:str="local_conservative"
	limits_verified_at:str|None=None

	def __post_init__(self)->None:
		values=(self.context_window_tokens,self.max_output_tokens,self.safety_margin_tokens,self.max_run_tokens)
		if any(type(value) is not int for value in values): raise ValueError("Token配置必须是整数且不能是布尔值")
		if self.context_window_tokens<=0 or self.max_output_tokens<=0 or self.max_run_tokens<=0 or self.safety_margin_tokens<0: raise ValueError("Token配置范围无效")
		if self.max_output_tokens+self.safety_margin_tokens>=self.context_window_tokens: raise ValueError("输出预留与安全余量必须小于上下文窗口")
		if self.context_window_tokens>10_000_000 or self.max_output_tokens>1_000_000 or self.max_run_tokens>10_000_000 or self.safety_margin_tokens>1_000_000: raise ValueError("Token配置超过安全上限")
		if not isinstance(self.estimator_id,str) or not self.estimator_id.strip(): raise ValueError("估算器身份不能为空")
		if not isinstance(self.limits_source,str) or not self.limits_source.strip(): raise ValueError("窗口来源不能为空")

	def to_dict(self)->dict[str,Any]:
		return {"context_window_tokens":self.context_window_tokens,"max_output_tokens":self.max_output_tokens,"safety_margin_tokens":self.safety_margin_tokens,"max_run_tokens":self.max_run_tokens,"estimator_id":self.estimator_id,"limits_source":self.limits_source,"limits_verified_at":self.limits_verified_at}


class HeuristicTokenEstimator:
	estimator_id="heuristic-json-v1"

	@staticmethod
	def _text_tokens(value:str)->int:
		# 保守估算：ASCII按字符块计数，非ASCII按字符计数，避免把中文当作一个词。
		if not isinstance(value,str): raise TypeError("待估算文本必须是字符串")
		return max(1,math.ceil(sum(1 if ord(char)>127 else 0.25 for char in value)))

	def estimate_messages(self,messages:tuple[dict[str,Any],...])->int:
		if not isinstance(messages,tuple): raise TypeError("messages必须是元组")
		return sum(self._text_tokens(json.dumps(message,ensure_ascii=False,separators=(",",":")))+4 for message in messages)

	def estimate_tools(self,tools:tuple[dict[str,Any],...])->int:
		if not isinstance(tools,tuple): raise TypeError("tools必须是元组")
		return sum(self._text_tokens(json.dumps(tool,ensure_ascii=False,separators=(",",":")))+8 for tool in tools)

	def estimate(self,messages:tuple[dict[str,Any],...],tools:tuple[dict[str,Any],...],response_format:str="text")->int:
		return self.estimate_messages(messages)+self.estimate_tools(tools)+self._text_tokens(response_format)+4


@dataclass(frozen=True,slots=True)
class TokenReservation:
	estimated_input_tokens:int
	max_output_tokens:int
	safety_margin_tokens:int
	reserved_tokens:int
	payload_hash:str


class TokenLedger:
	def __init__(self,config:ContextConfig)->None:
		self.config=config
		self.settled_tokens=0
		self.reserved_tokens=0
		self.unknown_calls=0

	@property
	def used_tokens(self)->int:
		return self.settled_tokens+self.reserved_tokens

	def reserve(self,estimated_input_tokens:int,payload:dict[str,Any])->TokenReservation:
		if type(estimated_input_tokens) is not int or estimated_input_tokens<0: raise ValueError("估算输入Token无效")
		reserved=estimated_input_tokens+self.config.max_output_tokens
		if estimated_input_tokens+self.config.max_output_tokens+self.config.safety_margin_tokens>self.config.context_window_tokens:
			raise ContextBudgetError("CONTEXT_BUDGET_EXCEEDED","当前模型上下文无法容纳本次请求",{"estimated_input_tokens":estimated_input_tokens,"max_output_tokens":self.config.max_output_tokens,"context_window_tokens":self.config.context_window_tokens})
		if self.used_tokens+reserved>self.config.max_run_tokens:
			raise ContextBudgetError("RUN_TOKEN_BUDGET_EXCEEDED","本次诊断累计Token预算已用尽",{"used_tokens":self.used_tokens,"reserved_tokens":reserved,"max_run_tokens":self.config.max_run_tokens})
		self.reserved_tokens+=reserved
		payload_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
		return TokenReservation(estimated_input_tokens,self.config.max_output_tokens,self.config.safety_margin_tokens,reserved,payload_hash)

	def settle(self,reservation:TokenReservation,reported_total:int|None,usage_status:str)->None:
		if reservation.reserved_tokens>self.reserved_tokens: raise RuntimeError("Token预占账本损坏")
		self.reserved_tokens-=reservation.reserved_tokens
		if usage_status=="complete" and reported_total is not None:
			self.settled_tokens+=reported_total
		else:
			self.settled_tokens+=reservation.reserved_tokens
			self.unknown_calls+=1
