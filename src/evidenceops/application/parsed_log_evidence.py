"""冻结日志工具结果，模型阅读内容与归档快照使用同一份正文。"""
import json
from datetime import datetime
from hashlib import sha256

from evidenceops.domain.evidence import Evidence,EvidenceSource


def parsed_logs_to_evidence(run_id,tool_call_id,data):
	if not isinstance(data,dict) or data.get("schema_version")!="log-evidence-v1": raise ValueError("invalid parsed log result")
	content=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
	if not 0<len(content)<=16000: raise ValueError("parsed log evidence exceeds snapshot limit")
	observed_at=datetime.fromisoformat(data["imported_at"])
	if observed_at.tzinfo is None: raise ValueError("import time requires timezone")
	identity=data["source_id"]
	events=data["events"]
	return (Evidence(evidence_id=f"{run_id}-{tool_call_id}",run_id=run_id,source=EvidenceSource.LOG,
		observed_at=observed_at,summary=f"日志来源{identity}：选取{len(events)}条事件，扫描状态{data['parser_status']}；观测时间为导入时间",
		source_ref=f"parsed-log:{identity}",content_hash=sha256(content.encode("utf-8")).hexdigest(),
		source_version="log-evidence-v1",content_snapshot=content,source_metadata={
			"source_id":identity,"source_role":data["source_role"],"observed_at_basis":"import_time",
			"input_sha256":data["input_sha256"],"hash_basis":data["hash_basis"],
			"parser_status":data["parser_status"],"selection":data["selection"],
			"line_ranges":[[event["line_start"],event["line_end"]] for event in events]}),)
