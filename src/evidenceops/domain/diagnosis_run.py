from enum import StrEnum
from datetime import UTC,datetime

class RunStatus(StrEnum):
	PENDING="pending"
	RUNNING="running"
	SUCCEEDED="succeeded"
	FAILED="failed"
	CANCELLED="cancelled"

# 终态不再接受流转，避免完成后的结果被后续执行覆盖。
ALLOWED_TRANSITIONS:dict[RunStatus,set[RunStatus]]={
	RunStatus.PENDING:{RunStatus.RUNNING,RunStatus.CANCELLED},
	RunStatus.RUNNING:{RunStatus.SUCCEEDED,RunStatus.FAILED,RunStatus.CANCELLED},
	RunStatus.SUCCEEDED:set(),
	RunStatus.FAILED:set(),
	RunStatus.CANCELLED:set(),
}


def can_transition(current_status:RunStatus,next_status:RunStatus)->bool:
	return next_status in ALLOWED_TRANSITIONS[current_status]

class DiagnosisRun:
	def __init__(self,run_id:str,request_id:str,description:str)->None:
		for field_name,value in (("run_id",run_id),("request_id",request_id),("description",description)):
			if not isinstance(value,str) or not value.strip():
				raise ValueError(f"{field_name}不能为空")
		self.run_id=run_id
		self.request_id=request_id
		self.description=description
		self._status=RunStatus.PENDING
		self.created_at=datetime.now(UTC)
		self.started_at:datetime|None=None
		self.finished_at:datetime|None=None
		self.error_code:str|None=None

	@property
	def status(self)->RunStatus:
		return self._status

	def transition(self,next_status:RunStatus,error_code:str|None=None)->None:
		# 验证通过后再修改状态和时间，防止非法流转留下半更新对象。
		if not isinstance(next_status,RunStatus):
			raise TypeError("next_status必须是RunStatus")
		if not can_transition(self._status,next_status):
			raise ValueError(f"不允许从{self._status.value}切换到{next_status.value}")
		if next_status is RunStatus.FAILED:
			if not isinstance(error_code,str) or not error_code.strip():
				raise ValueError("失败状态必须提供error_code")
		elif error_code is not None:
			raise ValueError("只有失败状态可以提供error_code")
		transition_time=datetime.now(UTC)
		if next_status is RunStatus.RUNNING:
			self.started_at=transition_time
		elif next_status in (RunStatus.SUCCEEDED,RunStatus.FAILED,RunStatus.CANCELLED):
			self.finished_at=transition_time
		if next_status is RunStatus.FAILED:
			self.error_code=error_code
		self._status=next_status
