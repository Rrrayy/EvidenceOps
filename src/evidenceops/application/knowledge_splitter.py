"""按段落边界切分知识文档，并让每个片段能回到不可变原文。"""
import re

from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,KnowledgeChunk


class KnowledgeSplitter:
	"""使用空行分段，超长段落按有重叠的字符窗口切分。"""
	_heading_pattern=re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
	_separator_pattern=re.compile(r"(?:\r\n|\n|\r)[ \t]*(?:\r\n|\n|\r)+")

	def split(self,version:DocumentVersion,chunk_set:ChunkSet)->tuple[KnowledgeChunk,...]:
		if not isinstance(version,DocumentVersion) or not isinstance(chunk_set,ChunkSet):
			raise TypeError("split需要DocumentVersion和ChunkSet")
		if chunk_set.version_id!=version.version_id:
			raise ValueError("ChunkSet不属于给定文档版本")
		content=version.content
		config=chunk_set.config
		chunks=[]
		heading_stack=[]
		heading_ranges=[]
		cursor=0
		while cursor<len(content):
			separator=self._separator_pattern.search(content,cursor)
			paragraph_end=separator.start() if separator is not None else len(content)
			paragraph_start=cursor
			while paragraph_start<paragraph_end and content[paragraph_start].isspace():
				paragraph_start+=1
			while paragraph_end>paragraph_start and content[paragraph_end-1].isspace():
				paragraph_end-=1
			if paragraph_start<paragraph_end:
				paragraph=content[paragraph_start:paragraph_end]
				if self._is_heading(paragraph):
					self._record_headings(paragraph,heading_stack)
					heading_ranges.append((paragraph_start,paragraph_end,paragraph))
					# 标题通过元数据提供上下文，原文仍由 DocumentVersion 完整保留。
				else:
					self._split_paragraph(version,chunk_set,content,paragraph_start,paragraph_end,
						tuple(title for _,title in heading_stack),chunks)
			if separator is None:
				break
			cursor=separator.end()
		if not chunks:
			raise ValueError("文档没有可切分的非空正文")
		if any(len(chunk.content)>config.chunk_size for chunk in chunks):
			raise RuntimeError("切分结果超过chunk_size")
		result=tuple(chunks)
		validate_chunk_coverage(version,result,tuple(heading_ranges))
		return result

	@classmethod
	def _is_heading(cls,paragraph:str)->bool:
		lines=paragraph.splitlines()
		return len(lines)==1 and cls._heading_pattern.match(lines[0].strip()) is not None

	def _split_paragraph(self,version:DocumentVersion,chunk_set:ChunkSet,content:str,start:int,end:int,
		heading_path:tuple[str,...],chunks:list[KnowledgeChunk])->None:
		# 不 strip 段落，以便 Chunk 的范围仍能精确还原原文。
		while start<end and content[start].isspace():
			start+=1
		while end>start and content[end-1].isspace():
			end-=1
		if start>=end:
			return
		config=chunk_set.config
		if end-start<=config.chunk_size:
			chunks.append(KnowledgeChunk.from_version(version,chunk_set,len(chunks),start,end,heading_path))
			return
		window_start=start
		while window_start<end:
			window_end=min(window_start+config.chunk_size,end)
			if window_end<end:
				natural_end=content.rfind(" ",window_start+1,window_end+1)
				if natural_end>window_start+config.chunk_size//2:
					window_end=natural_end
			chunks.append(KnowledgeChunk.from_version(version,chunk_set,len(chunks),window_start,window_end,heading_path))
			if window_end==end:
				break
			next_start=max(window_start+1,window_end-config.chunk_overlap)
			# 单个超长 token 无法按空格回退；强制推进，保证循环终止。
			window_start=next_start

	@classmethod
	def _record_headings(cls,paragraph:str,heading_stack:list[tuple[int,str]])->None:
		# 标题路径只作为元数据；标题原文仍留在 Chunk 正文和偏移中。
		match=cls._heading_pattern.match(paragraph.strip())
		if match is None:
			return
		level=len(match.group(1))
		title=match.group(2).strip()
		while heading_stack and heading_stack[-1][0]>=level:
			heading_stack.pop()
		heading_stack.append((level,title))


def validate_chunk_coverage(version:DocumentVersion,chunks:tuple[KnowledgeChunk,...],
	heading_ranges:tuple[tuple[int,int,str],...]=())->None:
	"""确保正文字符由 Chunk 覆盖、Markdown 标题由标题元数据覆盖。"""
	if not isinstance(version,DocumentVersion):
		raise TypeError("version必须是DocumentVersion")
	if not isinstance(chunks,tuple) or not chunks:
		raise ValueError("chunks必须是非空元组")
	content=version.content
	covered=bytearray(len(content))
	for start,end,title in heading_ranges:
		if not 0<=start<end<=len(content) or content[start:end]!=title:
			raise ValueError("标题范围与原文不一致")
		covered[start:end]=b"\x01"*(end-start)
	previous_start=-1
	for chunk in chunks:
		if not isinstance(chunk,KnowledgeChunk):
			raise TypeError("chunks只能包含KnowledgeChunk")
		if chunk.chunk_set.version_id!=version.version_id:
			raise ValueError("片段不属于给定文档版本")
		if chunk.start_offset<previous_start:
			raise ValueError("片段必须按原文位置排序")
		if content[chunk.start_offset:chunk.end_offset]!=chunk.content:
			raise ValueError("片段正文与原文范围不一致")
		covered[chunk.start_offset:chunk.end_offset]=b"\x01"*(chunk.end_offset-chunk.start_offset)
		previous_start=chunk.start_offset
	for index,character in enumerate(content):
		if not character.isspace() and not covered[index]:
			raise ValueError(f"原文非空白字符未被覆盖，位置:{index}")
