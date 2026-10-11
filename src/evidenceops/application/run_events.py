import logging
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime,timezone
from threading import RLock

from evidenceops.application.run_repository import RunPersistenceError


EventSink=Callable[[dict],None]


class EventPersistenceError(RunPersistenceError):
	def __init__(self,run_id:str)->None:
		super().__init__("event",run_id)


class RunEvents:
	def __init__(self,run_id:str,sink:EventSink|None=None,persist:EventSink|None=None)->None:
		self.run_id=run_id
		self._sink=sink
		self._sequence=0
		self._persist=persist
		self._closed=False
		self._failure:EventPersistenceError|None=None
		# 事件订阅者可能在model_started回调里请求取消，随后重入发布取消事件。
		self._lock=RLock()

	def emit(self,event_type:str,**data)->None:
		# 并发工具共享本次Run的序号；编号与入队在同一锁内，保证发送顺序。
		with self._lock:
			self.check()
			if self._closed:
				return
			event=self._build(event_type,data)
			if self._persist is not None:
				try:
					self._persist(event)
				except Exception as error:
					self._failure=EventPersistenceError(self.run_id)
					raise self._failure from error
			# 只有事务已提交才推进游标；客户端不能看到未提交事件。
			self._sequence=event["sequence"]
			self._deliver(event)

	def finish(self,event_type:str,data:dict,commit:Callable[[dict],None])->None:
		# 编号、终态事务与封闭共享锁，防止终止事件之后再插入工具或取消事件。
		with self._lock:
			self.check()
			if self._closed:
				raise RuntimeError("Run事件已经结束")
			event=self._build(event_type,data)
			commit(event)
			self._sequence=event["sequence"]
			self._closed=True
			self._deliver(event)

	def check(self)->None:
		# 即使旧的宽泛except改写了异常，Service也能识别真实持久化故障。
		with self._lock:
			if self._failure is not None:
				raise self._failure

	def locked(self):
		# 控制层统一按事件锁→控制锁的顺序接纳取消，避免回调重入时锁顺序反转。
		return self._lock

	def transport_failed(self,error_code:str)->None:
		with self._lock:
			self._closed=True
			# 传输错误没有持久化身份，不能被客户端当作可靠重放游标。
			self._deliver({"event":"stream_failed","sequence":self._sequence,"run_id":self.run_id,
				"occurred_at":datetime.now(timezone.utc).isoformat(),"data":{"error_code":error_code,
				"message":"诊断执行或保存失败，请查询历史状态"}})

	def _build(self,event_type:str,data:dict)->dict:
		return {"event":event_type,"sequence":self._sequence+1,"run_id":self.run_id,
			"occurred_at":datetime.now(timezone.utc).isoformat(),"data":deepcopy(data)}

	def _deliver(self,event:dict)->None:
		if self._sink is None:
			return
		try:
			# 回调可修改负载，必须避免它修改已经准备保存或测试比较的事件对象。
			self._sink(deepcopy(event))
		except Exception:
			logging.getLogger(__name__).warning("Run event delivery failed: %s",event["event"])
