import logging
from collections.abc import Callable
from datetime import datetime,timezone
from threading import Lock


EventSink=Callable[[dict],None]


class RunEvents:
	def __init__(self,run_id:str,sink:EventSink)->None:
		self.run_id=run_id
		self._sink=sink
		self._sequence=0
		self._lock=Lock()

	def emit(self,event_type:str,**data)->None:
		# 并发工具共享本次Run的序号；编号与入队在同一锁内，保证发送顺序。
		with self._lock:
			self._sequence+=1
			event={"event":event_type,"sequence":self._sequence,"run_id":self.run_id,
				"occurred_at":datetime.now(timezone.utc).isoformat(),"data":data}
			try:
				self._sink(event)
			except Exception:
				# 观测通道故障不能改变诊断结果；不记录事件负载中的业务数据。
				logging.getLogger(__name__).warning("Run event delivery failed: %s",event_type)
