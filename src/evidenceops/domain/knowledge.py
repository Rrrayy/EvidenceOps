"""定义知识文档的稳定身份；不读取文件、不切分正文、不访问数据库。"""
import json
from dataclasses import dataclass,field
from hashlib import sha256


def _require_text(value:str,name:str)->None:
	# 不自动 strip 正文，避免定位范围与实际保存内容不一致。
	if not isinstance(value,str) or not value.strip():
		raise ValueError(f"{name}必须是非空文本")


def _identity(kind:str,parts:tuple)->str:
	# JSON 保留字段边界，避免简单拼接使不同输入产生同一身份。
	content=json.dumps(parts,ensure_ascii=False,separators=(",",":"))
	return f"{kind}-{sha256(content.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True,slots=True)
class KnowledgeDocument:
	"""同一逻辑文档的身份；来源路径变化不应自动变成另一份文档。"""
	document_id:str
	title:str
	source_ref:str

	def __post_init__(self)->None:
		for name,value in (("document_id",self.document_id),("title",self.title),("source_ref",self.source_ref)):
			_require_text(value,name)


@dataclass(frozen=True,slots=True)
class DocumentVersion:
	"""保留原文与来源快照；版本身份由逻辑文档和原文内容决定。"""
	document_id:str
	source_ref:str
	content:str
	content_hash:str=field(init=False)
	version_id:str=field(init=False)

	def __post_init__(self)->None:
		for name,value in (("document_id",self.document_id),("source_ref",self.source_ref),("content",self.content)):
			_require_text(value,name)
		# frozen 防止构造完成后修改；派生字段只能在构造时设置。
		content_hash=sha256(self.content.encode("utf-8")).hexdigest()
		object.__setattr__(self,"content_hash",content_hash)
		object.__setattr__(self,"version_id",_identity("version",(self.document_id,content_hash)))


@dataclass(frozen=True,slots=True)
class SplitterConfig:
	"""字符窗口配置；算法版本必须覆盖实际切分行为的变化。"""
	algorithm_version:str="paragraph-window-v1"
	chunk_size:int=800
	chunk_overlap:int=100

	def __post_init__(self)->None:
		_require_text(self.algorithm_version,"algorithm_version")
		# bool 是 int 的子类，但 True 不应被接受为窗口大小。
		if type(self.chunk_size) is not int or self.chunk_size<=0:
			raise ValueError("chunk_size必须是正整数")
		if type(self.chunk_overlap) is not int or not 0<=self.chunk_overlap<self.chunk_size:
			raise ValueError("chunk_overlap必须是小于chunk_size的非负整数")


@dataclass(frozen=True,slots=True)
class ChunkSet:
	"""同一原文版本在指定切分规则下的片段集合身份。"""
	version_id:str
	config:SplitterConfig
	chunk_set_id:str=field(init=False)

	def __post_init__(self)->None:
		_require_text(self.version_id,"version_id")
		if not isinstance(self.config,SplitterConfig):
			raise TypeError("config必须是SplitterConfig")
		config=self.config
		object.__setattr__(self,"chunk_set_id",_identity("chunks",(self.version_id,config.algorithm_version,
			config.chunk_size,config.chunk_overlap)))


@dataclass(frozen=True,slots=True)
class KnowledgeChunk:
	"""原文切片；位置使用 Python 字符索引的左闭右开范围。"""
	chunk_set:ChunkSet
	chunk_index:int
	start_offset:int
	end_offset:int
	content:str
	heading_path:tuple[str,...]=()
	content_hash:str=field(init=False)
	chunk_id:str=field(init=False)

	def __post_init__(self)->None:
		if not isinstance(self.chunk_set,ChunkSet):
			raise TypeError("chunk_set必须是ChunkSet")
		if type(self.chunk_index) is not int or self.chunk_index<0:
			raise ValueError("chunk_index必须是非负整数")
		if type(self.start_offset) is not int or type(self.end_offset) is not int or not 0<=self.start_offset<self.end_offset:
			raise ValueError("片段范围必须满足0<=start_offset<end_offset")
		_require_text(self.content,"content")
		if len(self.content)!=self.end_offset-self.start_offset:
			raise ValueError("正文长度必须与字符范围一致")
		if len(self.content)>self.chunk_set.config.chunk_size:
			raise ValueError("片段超过chunk_size")
		if not isinstance(self.heading_path,tuple):
			raise TypeError("heading_path必须是元组")
		for heading in self.heading_path:
			_require_text(heading,"heading")
		content_hash=sha256(self.content.encode("utf-8")).hexdigest()
		object.__setattr__(self,"content_hash",content_hash)
		object.__setattr__(self,"chunk_id",_identity("chunk",(self.chunk_set.chunk_set_id,self.chunk_index,
			self.start_offset,self.end_offset,content_hash,self.heading_path)))

	@classmethod
	def from_version(cls,version:DocumentVersion,chunk_set:ChunkSet,chunk_index:int,start_offset:int,
		end_offset:int,heading_path:tuple[str,...]=())->"KnowledgeChunk":
		# 原文关联检查不能只看字符长度；相同长度的错误正文仍可能混入。
		if not isinstance(version,DocumentVersion) or not isinstance(chunk_set,ChunkSet):
			raise TypeError("必须提供DocumentVersion和ChunkSet")
		if version.version_id!=chunk_set.version_id:
			raise ValueError("片段集合不属于该文档版本")
		if type(start_offset) is not int or type(end_offset) is not int or not 0<=start_offset<end_offset<=len(version.content):
			raise ValueError("片段范围超出原文")
		return cls(chunk_set,chunk_index,start_offset,end_offset,version.content[start_offset:end_offset],heading_path)
