import re  # 校验 SHA-256 指纹格式
from dataclasses import dataclass  # 生成领域对象的初始化方法
from datetime import datetime  # 表示证据对应的观测时间
from enum import StrEnum  # 定义有限的证据来源类型


class EvidenceSource(StrEnum):  # 第一版支持的三类证据来源
	LOG="log"  # 应用日志
	METRIC="metric"  # 运行指标
	CONFIG="config"  # 服务配置


@dataclass(frozen=True,slots=True)  # 创建后不允许普通赋值修改字段
class Evidence:  					# 一条可追溯的事实记录
	evidence_id:str  				# 证据自身的唯一标识
	run_id:str 						# 这条证据属于哪一次诊断
	source:EvidenceSource  			# 来源类别
	observed_at:datetime  			# 源数据对应的观测时间
	summary:str  					# 对事实的简短描述，不写推测结论
	source_ref:str 					# 可回查的位置，例如日志文件与行号
	content_hash:str  				# 源内容的 SHA-256 十六进制指纹
	source_version:str|None=None  	# 来源版本未知时允许为 None

	def __post_init__(self)->None:  # dataclass 自动初始化完成后执行校验
		for field_name,value in (("evidence_id",self.evidence_id),("run_id",self.run_id),("summary",self.summary),("source_ref",self.source_ref)):  # 检查必填文本
			if not isinstance(value,str) or not value.strip():  # 拒绝错误类型和空白文本
				raise ValueError(f"{field_name}不能为空")  # 阻止不完整证据进入系统
		if not isinstance(self.source,EvidenceSource):  # 类型提示本身不会运行时校验
			raise TypeError("source必须是EvidenceSource")  # 拒绝裸字符串来源
		if not isinstance(self.observed_at,datetime):  # 先确认时间类型
			raise TypeError("observed_at必须是datetime")  # 拒绝字符串时间
		if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:  # 检查时间是否明确带时区
			raise ValueError("observed_at必须带时区")  # 避免跨机器解释时间时产生歧义
		if not isinstance(self.content_hash,str) or re.fullmatch(r"[0-9a-f]{64}",self.content_hash) is None:  # 检查 SHA-256 的格式
			raise ValueError("content_hash必须是64位小写十六进制SHA-256")  # 拒绝无效指纹
		if self.source_version is not None and (not isinstance(self.source_version,str) or not self.source_version.strip()):  # 检查可选版本
			raise ValueError("source_version不能是空白文本")  # 用 None 表示未知，不用空字符串