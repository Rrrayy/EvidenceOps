import pytest  # 使用 pytest 的异常断言功能

from evidenceops.domain.diagnosis_run import DiagnosisRun,RunStatus  # 导入待测试的领域对象


def test_valid_lifecycle()->None:  # 验证一条完整的正常路径
	run=DiagnosisRun("run-001","req-001","分析 RPC 超时")  # 创建一次诊断
	assert run.status is RunStatus.PENDING  # 新诊断应当等待执行
	run.transition(RunStatus.RUNNING)  # 开始运行
	assert run.status is RunStatus.RUNNING  # 确认状态已经改变
	run.transition(RunStatus.SUCCEEDED)  # 完成诊断
	assert run.status is RunStatus.SUCCEEDED  # 确认进入成功终态


def test_invalid_transition_preserves_status()->None:  # 验证非法流转不会污染状态
	run=DiagnosisRun("run-002","req-002","分析 RPC 超时")  # 创建仍在等待的诊断
	with pytest.raises(ValueError):  # 期待下一行抛出 ValueError
		run.transition(RunStatus.SUCCEEDED)  # 跳过运行阶段，属于非法流转
	assert run.status is RunStatus.PENDING  # 报错后必须保持原状态


def test_wrong_type_preserves_status()->None:  # 验证运行时拒绝错误类型
	run=DiagnosisRun("run-003","req-003","分析 RPC 超时")  # 创建仍在等待的诊断
	with pytest.raises(TypeError):  # 期待下一行抛出 TypeError
		run.transition("running")  # 故意传裸字符串，测试运行时边界
	assert run.status is RunStatus.PENDING  # 报错后必须保持原状态


def test_timestamps_follow_lifecycle()->None:  # 验证时间跟随状态变化
	run=DiagnosisRun("run-004","req-004","分析 RPC 超时")  # 创建一次诊断
	assert run.created_at.tzinfo is not None  # 创建时间必须带时区
	assert run.started_at is None  # 未运行时没有开始时间
	assert run.finished_at is None  # 未结束时没有结束时间
	run.transition(RunStatus.RUNNING)  # 开始运行
	assert run.started_at is not None  # 运行后应有开始时间
	assert run.finished_at is None  # 此时尚无结束时间
	run.transition(RunStatus.SUCCEEDED)  # 完成运行
	assert run.finished_at is not None  # 完成后应有结束时间


def test_cancel_before_start()->None:  # 验证等待中的任务可以直接取消
	run=DiagnosisRun("run-005","req-005","分析 RPC 超时")  # 创建一次诊断
	run.transition(RunStatus.CANCELLED)  # 开始前取消
	assert run.started_at is None  # 它确实从未开始
	assert run.finished_at is not None  # 但已经结束


def test_failure_requires_error_code()->None:  # 验证失败记录必须完整
	run=DiagnosisRun("run-006","req-006","分析 RPC 超时")  # 创建诊断运行
	run.transition(RunStatus.RUNNING)  # 先进入运行状态
	with pytest.raises(ValueError):  # 缺少错误码应被拒绝
		run.transition(RunStatus.FAILED)  # 尝试提交不完整的失败状态
	assert run.status is RunStatus.RUNNING  # 被拒绝后仍在运行
	assert run.finished_at is None  # 被拒绝后不能伪造结束时间
	run.transition(RunStatus.FAILED,error_code="TOOL_TIMEOUT")  # 携带错误码后合法失败
	assert run.status is RunStatus.FAILED  # 状态进入失败终态
	assert run.error_code=="TOOL_TIMEOUT"  # 错误码被保存
	assert run.finished_at is not None  # 结束时间被保存
