from enum import StrEnum
from datetime import UTC,datetime  # 使用带 UTC 时区的时间，避免本地时区歧义

class RunStatus(StrEnum):
	PENDING="pending"
	RUNNING="running"
	SUCCEEDED="succeeded"
	FAILED="failed"
	CANCELLED="cancelled"

ALLOWED_TRANSITIONS:dict[RunStatus,set[RunStatus]]={  # 当前状态到允许进入的状态的映射
	RunStatus.PENDING:{RunStatus.RUNNING,RunStatus.CANCELLED},  # 等待中的任务可以开始或取消
	RunStatus.RUNNING:{RunStatus.SUCCEEDED,RunStatus.FAILED,RunStatus.CANCELLED},  # 运行中的任务可以成功、失败或取消
	RunStatus.SUCCEEDED:set(),  # 成功是终态，不能继续流转
	RunStatus.FAILED:set(),  # 失败是终态，不能继续流转
	RunStatus.CANCELLED:set(),  # 取消是终态，不能继续流转
}


def can_transition(current_status:RunStatus,next_status:RunStatus)->bool:  # 判断一次状态变化是否合法
	return next_status in ALLOWED_TRANSITIONS[current_status]  # 目标状态在允许集合中才返回 True

class DiagnosisRun:  # 保存一次诊断的身份、输入和生命周期
	def __init__(self,run_id:str,request_id:str,description:str)->None:  # 创建诊断运行
		for field_name,value in (("run_id",run_id),("request_id",request_id),("description",description)):  # 逐项检查必填文本
			if not isinstance(value,str) or not value.strip():  # 拒绝非字符串及空白内容
				raise ValueError(f"{field_name}不能为空")  # 创建失败，不留下不完整对象
		self.run_id=run_id  # 诊断运行的标识
		self.request_id=request_id  # 创建它的请求标识
		self.description=description  # 用户提交的故障描述
		self._status=RunStatus.PENDING  # 初始状态是等待
		self.created_at=datetime.now(UTC)  # 使用带时区的创建时间
		self.started_at:datetime|None=None  # 尚未开始
		self.finished_at:datetime|None=None  # 尚未结束
		self.error_code:str|None=None  # 尚未失败

	@property  # 通过属性读取状态
	def status(self)->RunStatus:  # 返回当前状态
		return self._status  # 外部不能通过 status 直接赋值

	def transition(self,next_status:RunStatus,error_code:str|None=None)->None:  # 执行一次状态流转
		if not isinstance(next_status,RunStatus):  # 运行时检查目标状态的类型
			raise TypeError("next_status必须是RunStatus")  # 拒绝裸字符串
		if not can_transition(self._status,next_status):  # 先检查流转规则
			raise ValueError(f"不允许从{self._status.value}切换到{next_status.value}")  # 非法流转不修改对象
		if next_status is RunStatus.FAILED:  # 失败必须解释为稳定错误码
			if not isinstance(error_code,str) or not error_code.strip():  # 拒绝缺失或空白错误码
				raise ValueError("失败状态必须提供error_code")  # 不提交不完整的失败状态
		elif error_code is not None:  # 非失败状态不接受失败错误码
			raise ValueError("只有失败状态可以提供error_code")  # 避免成功却带失败码的矛盾记录
		transition_time=datetime.now(UTC)  # 所有检查通过后再取流转时间
		if next_status is RunStatus.RUNNING:  # 正式开始执行
			self.started_at=transition_time  # 保存开始时间
		elif next_status in (RunStatus.SUCCEEDED,RunStatus.FAILED,RunStatus.CANCELLED):  # 进入任一终态
			self.finished_at=transition_time  # 保存结束时间
		if next_status is RunStatus.FAILED:  # 保存失败原因类别
			self.error_code=error_code  # 不保存原始异常详情
		self._status=next_status  # 最后提交新状态