from collections.abc import Iterable  # 接收一组已收集的证据
from dataclasses import dataclass  # 定义不可随意修改的报告对象
from math import isfinite  # 排除 NaN 和无穷大置信度

from evidenceops.domain.evidence import Evidence  # 引用已有的证据类型


@dataclass(frozen=True,slots=True)  # 结论创建后不通过普通赋值修改
class DiagnosisClaim:  # 一条带证据引用的诊断判断
	text:str  # 根因或建议的文字
	evidence_ids:tuple[str,...]  # 支撑这条判断的证据 ID

	def __post_init__(self)->None:  # 检查判断自身的结构
		if not isinstance(self.text,str) or not self.text.strip():  # 判断文字不能为空
			raise ValueError("判断内容不能为空")  # 拒绝空判断
		if not isinstance(self.evidence_ids,tuple) or not self.evidence_ids:  # 至少引用一条证据
			raise ValueError("判断必须引用Evidence ID")  # 拒绝无证据判断
		for evidence_id in self.evidence_ids:  # 逐个检查引用
			if not isinstance(evidence_id,str) or not evidence_id.strip():  # ID 必须是非空文本
				raise ValueError("Evidence ID不能为空")  # 拒绝无效引用
		if len(set(self.evidence_ids))!=len(self.evidence_ids):  # 同一判断不重复引用同一 ID
			raise ValueError("Evidence ID不能重复")  # 拒绝重复引用


@dataclass(frozen=True,slots=True)  # 报告创建后不通过普通赋值修改
class DiagnosisReport:  			# 一次诊断的结构化报告
	run_id:str  					# 报告所属的诊断运行
	root_cause:DiagnosisClaim  		# 带证据引用的根因判断
	recommendations:tuple[DiagnosisClaim,...]  # 每条建议分别绑定证据
	confidence:float 	 			# 根因判断的置信度
	limitations:str  				# 说明数据覆盖范围和诊断限制

	def __post_init__(self)->None:  # 检查报告自身的结构
		if not isinstance(self.run_id,str) or not self.run_id.strip():  # 运行 ID 不能为空
			raise ValueError("run_id不能为空")  # 拒绝无所属运行的报告
		if not isinstance(self.root_cause,DiagnosisClaim):  # 根因必须是带引用的判断
			raise TypeError("root_cause必须是DiagnosisClaim")  # 拒绝裸字符串根因
		if not isinstance(self.recommendations,tuple) or not self.recommendations:  # 第一版至少给出一条建议
			raise ValueError("recommendations不能为空")  # 拒绝无建议报告
		for recommendation in self.recommendations:  # 检查每条建议的类型
			if not isinstance(recommendation,DiagnosisClaim):  # 建议也必须绑定证据
				raise TypeError("建议必须是DiagnosisClaim")  # 拒绝无引用建议
		if isinstance(self.confidence,bool) or not isinstance(self.confidence,(int,float)):  # 排除布尔值和非数字
			raise ValueError("confidence必须是数字")  # 拒绝错误类型
		if not isfinite(self.confidence) or not 0<=self.confidence<=1:  # 限定为有限的 0 到 1
			raise ValueError("confidence必须在0到1之间")  # 拒绝 NaN、无穷大和越界值
		if not isinstance(self.limitations,str) or not self.limitations.strip():  # 必须交代诊断限制
			raise ValueError("limitations不能为空")  # 避免把不完整诊断说成确定事实


def validate_report_evidence(report:DiagnosisReport,evidences:Iterable[Evidence])->None:  # 校验报告引用
	evidence_by_id:dict[str,Evidence]={}  # 建立 ID 到实际证据的索引
	for evidence in evidences:  # 扫描本次提供的证据
		if not isinstance(evidence,Evidence):  # 防止传入其他对象
			raise TypeError("evidences中包含非Evidence对象")  # 拒绝错误数据
		if evidence.evidence_id in evidence_by_id:  # 同一个 ID 不能指向两条记录
			raise ValueError(f"重复的Evidence ID: {evidence.evidence_id}")  # 拒绝歧义
		evidence_by_id[evidence.evidence_id]=evidence  # 保存可查找的证据
	for claim in (report.root_cause,*report.recommendations):  # 检查根因和每条建议
		for evidence_id in claim.evidence_ids:  # 检查该判断引用的每个 ID
			evidence=evidence_by_id.get(evidence_id)  # 按 ID 查找真实证据
			if evidence is None:  # 模型可能编造不存在的 ID
				raise ValueError(f"Evidence ID不存在: {evidence_id}")  # 拒绝虚构引用
			if evidence.run_id!=report.run_id:  # 证据不能来自另一轮诊断
				raise ValueError(f"Evidence不属于本次运行: {evidence_id}")  # 拒绝跨运行引用