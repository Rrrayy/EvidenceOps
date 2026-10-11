from dataclasses import dataclass

class EventHistoryError(RuntimeError):
	def __init__(self,status_code:int,error_code:str,message:str)->None:
		super().__init__(message)
		self.status_code=status_code
		self.error_code=error_code


@dataclass(frozen=True,slots=True)
class EventPage:
	run_id:str
	status:str
	events:tuple[dict,...]
	next_sequence:int
	max_sequence:int
	has_more:bool


def parse_event_cursor(run_id:str,after:int|None,last_event_id:str|None)->int:
	if last_event_id is None:
		return after if after is not None else 0
	# Run身份与序号分别校验，不能拿另一个Run的游标跳过当前事件。
	identity,separator,sequence=last_event_id.strip().rpartition(":")
	if not separator or identity!=run_id or len(sequence)>19 or not sequence.isascii() or not sequence.isdecimal():
		raise EventHistoryError(422,"INVALID_ARGUMENTS","Last-Event-ID必须为当前run_id:非负序号")
	parsed=int(sequence)
	if parsed>9223372036854775807:
		raise EventHistoryError(422,"INVALID_ARGUMENTS","事件序号超过BIGINT范围")
	if after is not None and after!=parsed:
		raise EventHistoryError(422,"INVALID_ARGUMENTS","after与Last-Event-ID不一致")
	return parsed


def load_event_page(persistence,run_id:str,after:int=0,limit:int=100)->EventPage:
	run_id=run_id.strip()
	if not run_id or isinstance(after,bool) or not isinstance(after,int) or not 0<=after<=9223372036854775807:
		raise EventHistoryError(422,"INVALID_ARGUMENTS","run_id不能为空且after必须为非负整数")
	if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=1000:
		raise EventHistoryError(422,"INVALID_ARGUMENTS","limit必须在1至1000之间")
	if persistence is None:
		raise EventHistoryError(503,"PERSISTENCE_DISABLED","当前未启用事件持久化")
	with persistence.transaction() as transaction:
		# 先读状态再读事件；终态与终止事件原子提交，避免先读旧事件再读新终态而早退。
		run=transaction.run.get(run_id)
		if run is None:
			raise EventHistoryError(404,"RUN_NOT_FOUND","诊断运行不存在")
		maximum=transaction.trace_event.get_max_sequence(run_id)
		if after>maximum:
			raise EventHistoryError(409,"INVALID_EVENT_CURSOR","游标超过已保存的最大序号")
		# 多读一条判断分页，不将并发增长中的最大序号当作固定快照。
		items=transaction.trace_event.list_by_run(run_id,after,limit+1)
		for expected,item in enumerate(items,start=after+1):
			if item["sequence"]!=expected:
				raise EventHistoryError(409,"EVENT_HISTORY_GAP","事件序号存在缺口，无法完整补发")
		events=items[:limit]
		maximum=max(maximum,items[-1]["sequence"] if items else 0)
		return EventPage(run_id,run.status.value,events,events[-1]["sequence"] if events else after,
			maximum,len(items)>limit)
