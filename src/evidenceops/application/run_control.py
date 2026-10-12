from threading import Event,Lock,RLock
from contextlib import nullcontext
from time import monotonic

from evidenceops.application.run_events import RunEvents
from evidenceops.application.run_budget import RunBudget
from evidenceops.domain.diagnosis_run import RunStatus


class RunCancelled(RuntimeError):
	pass


class RunControl:
	def __init__(self,events:RunEvents|None=None,budget:RunBudget|None=None)->None:
		self._signal=Event()
		# 观测回调可能同线程重复请求取消，允许重入但不重复发布请求事件。
		self._lock=RLock()
		self._terminal:RunStatus|None=None
		self._events=events
		self._budget=budget

	def check(self)->None:
		if self._signal.is_set():
			raise RunCancelled("诊断已请求取消")
		if self._budget is not None:
			self._budget.check()

	def wait(self,seconds:float)->bool:
		deadline=monotonic()+max(0,seconds)
		while True:
			remaining=max(0,deadline-monotonic())
			if self._budget is not None:
				self._budget.check()
			if remaining<=0:
				return self._signal.is_set()
			if self._signal.wait(self._budget.limit(remaining) if self._budget is not None else remaining):
				return True
			# Windows等待可能因时间精度提前返回；必须重查时钟，不能误当作工作已完成。

	def request_cancel(self)->dict:
		# 终态已认领时不等待正在提交的事件锁，取消接口应立即返回finalizing。
		with self._lock:
			if self._terminal is not None:
				return {"cancellation_requested":False,"phase":"finalizing","target_status":self._terminal.value}
		with self._events.locked() if self._events is not None else nullcontext():
			return self._request_cancel()

	def _request_cancel(self)->dict:
		with self._lock:
			if self._terminal is not None:
				return {"cancellation_requested":False,"phase":"finalizing","target_status":self._terminal.value}
			already_requested=self._signal.is_set()
			# 设置意图和事件在终态认领前完成，避免cancelled事件先于requested事件。
			self._signal.set()
			if not already_requested and self._events is not None:
				self._events.emit("run_cancel_requested")
			return {"cancellation_requested":True,"already_requested":already_requested,"phase":"cancellation_requested"}

	def claim_terminal(self,status:RunStatus)->RunStatus:
		if status not in (RunStatus.SUCCEEDED,RunStatus.FAILED,RunStatus.CANCELLED):
			raise ValueError("只能认领终态")
		# 锁只保护决定权，不跨越数据库提交；认领后不再接纳取消。
		with self._lock:
			if self._terminal is None:
				self._terminal=RunStatus.CANCELLED if self._signal.is_set() else status
			return self._terminal


class RunRegistry:
	def __init__(self)->None:
		self._lock=Lock()
		self._runs:dict[str,RunControl]={}

	def register(self,run_id:str,control:RunControl)->None:
		with self._lock:
			if run_id in self._runs:
				raise ValueError("Run已在执行")
			self._runs[run_id]=control

	def get(self,run_id:str)->RunControl|None:
		with self._lock:
			return self._runs.get(run_id)

	def remove(self,run_id:str)->None:
		with self._lock:
			self._runs.pop(run_id,None)
