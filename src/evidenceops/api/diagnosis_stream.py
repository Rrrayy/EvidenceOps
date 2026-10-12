import asyncio
import json
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from threading import BoundedSemaphore,Lock
from time import monotonic
from uuid import uuid4


TERMINAL_EVENTS={"run_completed","run_failed","run_cancelled","stream_failed"}


def encode_event(event:dict)->str:
	# 单行JSON会转义文本中的换行，不能让业务文本注入额外SSE事件。
	payload=json.dumps(event,ensure_ascii=False,separators=(",",":"))
	identity="" if event["event"]=="stream_failed" else f"id: {event['run_id'] or 'stream'}:{event['sequence']}\n"
	return f"{identity}event: {event['event']}\ndata: {payload}\n\n"


class EventChannel:
	def __init__(self,capacity:int=256)->None:
		if capacity<1:
			raise ValueError("事件队列容量必须大于0")
		self._capacity=capacity
		self._events=deque()
		self._lock=Lock()
		self._closed=False
		self._terminal=False  #标记是否收到终止事件

	def publish(self,event:dict)->None:
		with self._lock:
			if self._closed or self._terminal:
				return
			if len(self._events)>=self._capacity:
				# 溢出显式终止观测连接，不能悄悄丢事件却展示完整成功链路。
				self._events.clear()
				event={**event,"event":"stream_failed","data":{"error_code":"EVENT_BUFFER_OVERFLOW",
					"message":"客户端消费过慢，过程流已停止；诊断继续执行"}}
			self._events.append(event)
			self._terminal=event["event"] in TERMINAL_EVENTS

	def pop(self)->dict|None:
		with self._lock:
			return self._events.popleft() if self._events else None

	def close(self)->None:
		with self._lock:
			self._closed=True
			self._events.clear()

	async def stream(self,heartbeat_seconds:float=15,poll_seconds:float=0.05):
		if heartbeat_seconds<=0 or poll_seconds<=0:
			raise ValueError("心跳和轮询间隔必须大于0")
		last_sent=monotonic()
		try:
			yield ": connected\n\n"
			while True:
				event=self.pop()
				if event is not None:
					yield encode_event(event)
					last_sent=monotonic()
					if event["event"] in TERMINAL_EVENTS:
						break
				elif monotonic()-last_sent>=heartbeat_seconds:
					yield ": heartbeat\n\n"
					last_sent=monotonic()
				else:
					# 只轮询内存队列，不阻塞事件循环，也不轮询数据库或模型接口。
					await asyncio.sleep(poll_seconds)
		finally:
			# 网络取消只关闭观测通道；后台工作继续，但不能再积累无人读取的事件。
			self.close()


class StreamBusyError(RuntimeError):
	pass


class DiagnosisStreamRunner:
	def __init__(self,service,max_runs:int=4)->None:
		if max_runs<1:
			raise ValueError("并发诊断数量必须大于0")
		self._service=service
		self._slots=BoundedSemaphore(max_runs)
		self._executor=ThreadPoolExecutor(max_workers=max_runs,thread_name_prefix="diagnosis-stream")

	def start(self,description:str,service=None)->EventChannel:
		# 限制诊断数量而非连接数量；断连不能立即释放仍在工作的任务槽位。
		if not self._slots.acquire(blocking=False):
			raise StreamBusyError("流式诊断并发已达上限，请稍后重试")
		channel=EventChannel()
		request_id=f"req-{uuid4()}"
		def execute():
			try:
				(service or self._service).execute(request_id,description,event_sink=channel.publish)
			except Exception:
				# Service已经发送终止事件时publish会忽略此兜底；不泄露原始异常。
				logging.getLogger(__name__).warning("Streaming diagnosis failed: %s",request_id)
				channel.publish({"event":"stream_failed","sequence":1,"run_id":None,
					"occurred_at":datetime.now(timezone.utc).isoformat(),
					"data":{"error_code":"DIAGNOSIS_EXECUTION_FAILED","message":"诊断执行失败"}})
			finally:
				self._slots.release()
		try:
			self._executor.submit(execute)
		except Exception:
			self._slots.release()
			raise
		return channel

	def close(self)->None:
		# 先等已开始诊断完成，再关闭共享Provider/Runtime，避免关闭正在使用的资源。
		self._executor.shutdown(wait=True)
