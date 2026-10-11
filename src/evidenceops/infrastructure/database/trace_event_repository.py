from copy import deepcopy
from datetime import datetime

from sqlalchemy import func,select
from sqlalchemy.orm import Session

from evidenceops.infrastructure.database.models import TraceEventRow


class SqlAlchemyTraceEventRepository:
	def __init__(self,session:Session)->None:
		self._session=session

	def create(self,event:dict)->None:
		sequence=event["sequence"]
		if isinstance(sequence,bool) or not isinstance(sequence,int) or sequence<1:
			raise ValueError("事件序号必须是正整数")
		occurred_at=datetime.fromisoformat(event["occurred_at"])
		if occurred_at.utcoffset() is None:
			raise ValueError("事件时间必须包含时区")
		# 深拷贝避免调用方随后修改字典，改变尚未flush的事件内容。
		self._session.add(TraceEventRow(event_id=f"{event['run_id']}:{sequence}",run_id=event["run_id"],
			sequence=sequence,event_type=event["event"],payload=deepcopy(event["data"]),occurred_at=occurred_at))
		self._session.flush()

	def list_by_run(self,run_id:str,after_sequence:int=0,limit:int=100)->tuple[dict,...]:
		if not isinstance(run_id,str) or not run_id.strip():
			raise ValueError("run_id不能为空")
		if isinstance(after_sequence,bool) or not isinstance(after_sequence,int) or after_sequence<0:
			raise ValueError("事件游标必须是非负整数")
		if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=1001:
			# 查询服务最多对公开1000条分页额外读取一条，判断has_more。
			raise ValueError("仓储读取大小必须在1至1001之间")
		query=select(TraceEventRow).where(TraceEventRow.run_id==run_id,TraceEventRow.sequence>after_sequence)
		rows=self._session.scalars(query.order_by(TraceEventRow.sequence).limit(limit))
		return tuple({"event":row.event_type,"run_id":row.run_id,"sequence":row.sequence,
			"occurred_at":row.occurred_at.isoformat(),"data":deepcopy(row.payload)} for row in rows)

	def get_max_sequence(self,run_id:str)->int:
		return self._session.scalar(select(func.max(TraceEventRow.sequence)).where(TraceEventRow.run_id==run_id)) or 0
