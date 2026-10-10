from collections.abc import Callable
from math import isfinite
from time import monotonic


class RunBudgetExceeded(TimeoutError):
	pass


class RunBudget:
	def __init__(self,seconds:float,clock:Callable[[],float]=monotonic)->None:
		if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not isfinite(seconds) or seconds<=0:
			raise ValueError("诊断预算必须是有限正数")
		self._clock=clock
		self._deadline=clock()+seconds

	def remaining(self)->float:
		return max(0,self._deadline-self._clock())

	def check(self)->None:
		if self.remaining()<=0:
			raise RunBudgetExceeded("诊断整体执行预算已耗尽")

	def limit(self,seconds:float)->float:
		remaining=self.remaining()
		if remaining<=0:
			raise RunBudgetExceeded("诊断整体执行预算已耗尽")
		return min(seconds,remaining)
