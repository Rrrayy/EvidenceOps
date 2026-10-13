import pytest

from evidenceops.application.knowledge_splitter import KnowledgeSplitter,validate_chunk_coverage
from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,SplitterConfig


def split_text(content:str,chunk_size:int=80,chunk_overlap:int=10):
	version=DocumentVersion("rpc-runbook","knowledge/rpc.md",content)
	chunk_set=ChunkSet(version.version_id,SplitterConfig(chunk_size=chunk_size,chunk_overlap=chunk_overlap))
	return version,KnowledgeSplitter().split(version,chunk_set)


def test_keeps_paragraphs_and_original_character_ranges()->None:
	content="# RPC排障\r\n\r\n第一段说明超时现象。\r\n\r\n第二段要求检查调用链。\r\n"
	version,chunks=split_text(content)
	assert len(chunks)==2
	assert [chunk.content for chunk in chunks]==["第一段说明超时现象。","第二段要求检查调用链。"]
	assert all(version.content[chunk.start_offset:chunk.end_offset]==chunk.content for chunk in chunks)
	assert [chunk.heading_path for chunk in chunks]==[("RPC排障",),("RPC排障",)]


def test_long_paragraph_splits_with_configured_overlap_and_bound()->None:
	content="这是一个很长的排障段落，"*18
	version,chunks=split_text(content,chunk_size=48,chunk_overlap=9)
	assert len(chunks)>1
	assert all(len(chunk.content)<=48 for chunk in chunks)
	assert all(left.end_offset-right.start_offset==9 for left,right in zip(chunks,chunks[1:]))
	assert all(left.content[-9:]==right.content[:9] for left,right in zip(chunks,chunks[1:]))


def test_splitter_preserves_all_non_whitespace_source_characters()->None:
	content="# 调用\n\n检查线程池与队列。\n\n## 重试\n\n配置允许重试不代表已经发生重试。\n"
	version,chunks=split_text(content,chunk_size=12,chunk_overlap=3)
	validate_chunk_coverage(version,chunks,((0,4,"# 调用"),(17,22,"## 重试")))
	assert "配置允许重试" in "".join(chunk.content for chunk in chunks)
	assert any(chunk.heading_path==("调用","重试") for chunk in chunks)


def test_no_paragraph_separator_and_unbroken_token_terminate()->None:
	content="x"*101
	version,chunks=split_text(content,chunk_size=20,chunk_overlap=5)
	assert all(len(chunk.content)<=20 for chunk in chunks)
	validate_chunk_coverage(version,chunks)


@pytest.mark.parametrize("content",["\n \r\n\t","\n\n\r\n"])
def test_rejects_whitespace_only_document(content)->None:
	with pytest.raises(ValueError,match="content"):
		DocumentVersion("empty","knowledge/empty.md",content)


def test_rejects_chunk_set_from_another_version()->None:
	version=DocumentVersion("doc","knowledge/doc.md","正文")
	other=DocumentVersion("doc","knowledge/doc.md","其他正文")
	with pytest.raises(ValueError,match="不属于"):
		KnowledgeSplitter().split(version,ChunkSet(other.version_id,SplitterConfig()))


def test_coverage_validator_detects_missing_source_text()->None:
	version,chunks=split_text("第一段。\n\n第二段。")
	with pytest.raises(ValueError,match="未被覆盖"):
		validate_chunk_coverage(version,(chunks[0],))


def test_coverage_validator_rejects_wrong_order()->None:
	version,chunks=split_text("第一段。\n\n第二段。")
	with pytest.raises(ValueError,match="按原文位置排序"):
		validate_chunk_coverage(version,tuple(reversed(chunks)))
