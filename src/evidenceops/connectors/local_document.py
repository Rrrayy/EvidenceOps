"""读取受控目录中的知识文本；不解析日志、不创建版本或 Evidence。"""
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


class DocumentLoadError(RuntimeError):
	def __init__(self,code:str,message:str)->None:
		super().__init__(message)
		self.code=code


@dataclass(frozen=True,slots=True)
class DocumentInput:
	"""加载结果；raw_hash 校验文件字节，正文哈希留给版本层计算。"""
	source_ref:str
	content:str
	byte_count:int
	raw_hash:str


class LocalDocumentLoader:
	def __init__(self,allowed_root:Path,max_bytes:int=2*1024*1024)->None:
		if type(max_bytes) is not int or max_bytes<=0:
			raise ValueError("max_bytes必须是正整数")
		try:
			root=Path(allowed_root).resolve(strict=True)
		except (OSError,ValueError) as error:
			raise DocumentLoadError("INVALID_ROOT","知识目录不存在或无法访问") from error
		if not root.is_dir():
			raise DocumentLoadError("INVALID_ROOT","知识根路径必须是目录")
		self._root=root
		self._max_bytes=max_bytes

	def load(self,relative_path:str,*,purpose:str)->DocumentInput:
		# 用途由调用入口明确指定，扩展名不能证明内容是手册还是运行日志。
		if purpose!="knowledge":
			raise DocumentLoadError("INVALID_PURPOSE","当前加载器仅支持明确指定的knowledge用途")
		if not isinstance(relative_path,str) or not relative_path.strip():
			raise DocumentLoadError("INVALID_PATH","知识文件路径不能为空")
		requested=Path(relative_path)
		if requested.is_absolute() or requested.drive or requested.root:
			raise DocumentLoadError("INVALID_PATH","必须使用知识目录内的相对路径")
		try:
			# 解析已有符号链接，拒绝目录穿越以及指向根目录之外的链接。
			path=(self._root/requested).resolve(strict=True)
			if not path.is_relative_to(self._root):
				raise DocumentLoadError("OUTSIDE_ROOT","文件不在允许的知识目录内")
			if path.suffix.lower() not in (".md",".txt"):
				raise DocumentLoadError("UNSUPPORTED_FORMAT","仅支持Markdown和TXT知识文件")
			if not path.is_file():
				raise DocumentLoadError("NOT_REGULAR_FILE","知识来源必须是普通文件")
			with path.open("rb") as stream:
				file_info=os.fstat(stream.fileno())
				if not stat.S_ISREG(file_info.st_mode):
					raise DocumentLoadError("NOT_REGULAR_FILE","知识来源必须是普通文件")
				if file_info.st_size>self._max_bytes:
					raise DocumentLoadError("DOCUMENT_TOO_LARGE","知识文件超过字节大小限制")
				# stat 后文件仍可能增长；多读一个字节检测越限，禁止无界 read。
				raw=stream.read(self._max_bytes+1)
			if len(raw)>self._max_bytes:
				raise DocumentLoadError("DOCUMENT_TOO_LARGE","知识文件超过字节大小限制")
		except DocumentLoadError:
			raise
		except (OSError,ValueError) as error:
			raise DocumentLoadError("DOCUMENT_READ_FAILED","知识文件不存在或无法读取") from error
		try:
			# 只移除开头的 UTF-8 BOM，不转换换行、不 strip 正文、不猜测 GBK。
			content=raw.decode("utf-8-sig",errors="strict")
		except UnicodeDecodeError as error:
			raise DocumentLoadError("INVALID_ENCODING","知识文件必须使用UTF-8编码") from error
		if not content.strip():
			raise DocumentLoadError("EMPTY_DOCUMENT","知识文件正文不能为空")
		return DocumentInput(path.relative_to(self._root).as_posix(),content,len(raw),sha256(raw).hexdigest())
