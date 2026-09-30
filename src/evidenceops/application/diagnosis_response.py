from typing import Any  # 描述转换后的通用字典值

from evidenceops.application.diagnosis_service import DiagnosisExecution  # 接收已有的执行结果


def to_response(result:DiagnosisExecution)->dict[str,Any]:  # 将内部对象转换为可编码为 JSON 的数据
	run=result.run  # 取出本次诊断的运行对象
	report=result.report  # 取出报告；失败时为 None
	evidence_items=[]  # 准备输出证据列表
	for evidence in result.evidences:  # 逐条转换 Evidence
		evidence_items.append({  # 添加一条普通字典
			"evidence_id":evidence.evidence_id,  # 保留引用所需的 ID
			"source":evidence.source.value,  # 将枚举变为字符串
			"observed_at":evidence.observed_at.isoformat(),  # 将时间变为带时区文本
			"summary":evidence.summary,  # 保留事实摘要
			"source_ref":evidence.source_ref,  # 保留回查位置
			"content_hash":evidence.content_hash,  # 保留内容指纹
			"source_version":evidence.source_version,  # 保留来源版本或 None
		})  # 完成当前证据
	report_item=None  # 失败时报告明确为 null
	if report is not None:  # 只有成功产生报告时才转换
		report_item={  # 构造报告字典
			"run_id":report.run_id,  # 保留报告所属运行
			"root_cause":{  # 转换根因判断
				"text":report.root_cause.text,  # 根因文字
				"evidence_ids":list(report.root_cause.evidence_ids),  # 元组转换为数组
			},  # 完成根因
			"recommendations":[  # 逐条转换建议
				{"text":claim.text,"evidence_ids":list(claim.evidence_ids)}  # 每条建议保留自己的引用
				for claim in report.recommendations  # 遍历已有建议
			],  # 完成建议列表
			"confidence":report.confidence,  # 保留未校准的置信度值
			"limitations":report.limitations,  # 保留诊断限制
		}  # 完成报告
	return {  # 返回统一的成功或失败结构
		"run_id":run.run_id,  # 本次运行 ID
		"request_id":run.request_id,  # 原请求 ID
		"status":run.status.value,  # 枚举转换为字符串
		"error_code":run.error_code,  # 成功为 None，失败为稳定错误码
		"created_at":run.created_at.isoformat(),  # 创建时间
		"started_at":run.started_at.isoformat() if run.started_at is not None else None,  # 开始时间或 None
		"finished_at":run.finished_at.isoformat() if run.finished_at is not None else None,  # 结束时间或 None
		"evidences":evidence_items,  # 本次收集到的证据
		"report":report_item,  # 成功报告或 None
	}  # 完成输出