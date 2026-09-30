from hashlib import sha256  # 独立计算预期的原始日志指纹

from fastapi.testclient import TestClient  # 在测试进程内调用 HTTP 路由

from evidenceops.api.mock_diagnosis import app  # 使用已注册两个 Mock 路由的应用


def test_request_log_produces_evidence_from_submitted_line()->None:  # 验证请求日志真正参与诊断
	raw_line="2026-10-01T10:00:00+08:00 RPC timeout active_threads=64 thread_limit=64 pending_tasks=128"  # 准备确定的原始行
	client=TestClient(app)  # 创建测试客户端
	response=client.post("/api/v1/mock/log-diagnosis",json={"description":"排查 RPC 超时","log_text":raw_line})  # 提交本次日志
	body=response.json()  # 解析响应
	assert response.status_code==200  # 匹配案例应完成诊断
	assert body["status"]=="succeeded"  # Service 完成状态流转
	assert len(body["evidences"])==1  # 目前只从请求中提取一条日志证据
	assert body["evidences"][0]["content_hash"]==sha256(raw_line.encode("utf-8")).hexdigest()  # 哈希必须来自本次提交的原文
	assert body["evidences"][0]["observed_at"]=="2026-10-01T10:00:00+08:00"  # 保留日志事件时间
	assert body["report"]["root_cause"]["evidence_ids"]==[body["evidences"][0]["evidence_id"]]  # 根因引用实际输出的证据


def test_unmatched_log_does_not_receive_fixed_diagnosis()->None:  # 验证不匹配日志不会被套入固定结论
	client=TestClient(app)  # 创建测试客户端
	response=client.post("/api/v1/mock/log-diagnosis",json={"description":"排查 RPC 超时","log_text":"2026-10-01T10:00:00+08:00 RPC timeout active_threads=2 thread_limit=64 pending_tasks=0"})  # 提交未满载日志
	body=response.json()  # 解析失败响应
	assert response.status_code==503  # 暂时沿用现有 Mock 接口的失败状态码
	assert body["error_code"]=="EVIDENCE_INSUFFICIENT"  # 当前模式下证据不满足诊断条件
	assert body["evidences"]==[]  # 不伪造 64/64 证据
	assert body["report"] is None  # 不交付固定根因