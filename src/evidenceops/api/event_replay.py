import asyncio
from datetime import datetime,UTC
from threading import BoundedSemaphore,Lock
from time import monotonic

from evidenceops.api.diagnosis_stream import encode_event
from evidenceops.application.event_history import EventHistoryError,load_event_page


class ReplayBusyError(RuntimeError):
	pass


class EventReplay:
	def __init__(self,persistence,max_connections:int=16,poll_seconds:float=0.5,
		heartbeat_seconds:float=15,page_size:int=100)->None:
		if max_connections<1 or poll_seconds<=0 or heartbeat_seconds<=0 or not 1<=page_size<=999:
			raise ValueError("重放连接、间隔和分页配置无效")
		self._persistence=persistence
		self._slots=BoundedSemaphore(max_connections)
		self.poll_seconds=poll_seconds
		self.heartbeat_seconds=heartbeat_seconds
		self.page_size=page_size

	def reserve(self):
		if not self._slots.acquire(blocking=False):
			raise ReplayBusyError("事件观察连接已达上限")
		return ReplayLease(self)


class ReplayLease:
	def __init__(self,replay:EventReplay)->None:
		self._replay=replay
		self._closed=False
		self._lock=Lock()

	def close(self)->None:
		# 生成器finally与响应后台清理可能同时调用，不能重复释放Semaphore。
		with self._lock:
			if not self._closed:
				self._closed=True
				self._replay._slots.release()

	async def stream(self,first_page):
		page=first_page
		cursor=page.events[0]["sequence"]-1 if page.events else page.next_sequence
		last_sent=monotonic()
		try:
			yield ": connected\n\n"
			while True:
				for item in page.events:
					yield encode_event(item)
					cursor=item["sequence"]
					last_sent=monotonic()
					if item["event"] in {"run_completed","run_failed","run_cancelled"}:
						return
				# 终态游标已在末尾，或旧Run无事件，都正常关闭且不补造终止事件。
				if page.status in {"succeeded","failed","cancelled"} and not page.has_more:
					return
				if not page.has_more:
					if monotonic()-last_sent>=self._replay.heartbeat_seconds:
						yield ": heartbeat\n\n"
						last_sent=monotonic()
					await asyncio.sleep(self._replay.poll_seconds)
				try:
					# 每轮短事务读完就关闭Session，网络发送和等待不占连接。
					page=await asyncio.to_thread(load_event_page,self._replay._persistence,page.run_id,
						cursor,self._replay.page_size)
				except Exception as error:
					code=error.error_code if isinstance(error,EventHistoryError) else "PERSISTENCE_FAILED"
					yield encode_event({"event":"stream_failed","run_id":page.run_id,"sequence":cursor,
						"occurred_at":datetime.now(UTC).isoformat(),"data":{"error_code":code,
						"message":"事件读取失败，请查询历史状态后重连"}})
					return
		finally:
			# 只释放观察连接，不设置RunControl，不启动或取消任何诊断。
			self.close()
