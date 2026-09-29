from datetime import UTC,datetime  # 构造带 UTC 时区的测试时间
from hashlib import sha256  # 模拟 Connector 对源内容计算指纹

import pytest  # 验证失败路径

from evidenceops.domain.evidence import Evidence,EvidenceSource  # 导入待测试对象


def test_evidence_preserves_provenance()->None:  # 验证正常证据保留来源信息
	raw_log="active_threads=64 limit=64"  # 测试用的原始日志内容
	content_hash=sha256(raw_log.encode("utf-8")).hexdigest()  # 从原文计算指纹
	evidence=Evidence("ev-001","run-001",EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限","rpc.log:120",content_hash,"deploy-001")  # 建立证据
	assert evidence.evidence_id=="ev-001"  # 后续报告可通过 ID 引用它
	assert evidence.source_ref=="rpc.log:120"  # 来源位置可回查
	assert evidence.content_hash==content_hash  # 指纹被原样保存


def test_evidence_rejects_missing_source_ref()->None:  # 验证无法回查的证据被拒绝
	content_hash=sha256(b"active_threads=64").hexdigest()  # 准备合法指纹
	with pytest.raises(ValueError):  # 期待构造失败
		Evidence("ev-002","run-001",EvidenceSource.LOG,datetime(2026,9,30,10,0,tzinfo=UTC),"活跃线程达到上限","",content_hash)  # 故意不给来源位置