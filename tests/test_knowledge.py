from dataclasses import FrozenInstanceError,replace

import pytest

from evidenceops.domain.knowledge import ChunkSet,DocumentVersion,KnowledgeChunk,KnowledgeDocument,SplitterConfig


def make_version()->DocumentVersion:
	return DocumentVersion("rpc-runbook","samples/knowledge/rpc.md","# RPC超时\n检查调用链，不能仅靠配置确认重试。")


def test_version_identity_tracks_document_and_exact_content()->None:
	version=make_version()
	assert replace(version).version_id==version.version_id
	assert replace(version,content=version.content+"\n").version_id!=version.version_id
	assert replace(version,document_id="another-runbook").version_id!=version.version_id
	# 来源搬迁不改变内容身份，但每个版本对象仍保存自己的来源快照。
	assert replace(version,source_ref="archive/rpc.md").version_id==version.version_id
	assert version.content.startswith("# RPC")


def test_splitter_changes_produce_distinct_chunk_sets()->None:
	version=make_version()
	chunk_set=ChunkSet(version.version_id,SplitterConfig())
	assert ChunkSet(version.version_id,SplitterConfig()).chunk_set_id==chunk_set.chunk_set_id
	for config in (SplitterConfig(chunk_size=900),SplitterConfig(chunk_overlap=0),SplitterConfig(algorithm_version="paragraph-window-v2")):
		assert ChunkSet(version.version_id,config).chunk_set_id!=chunk_set.chunk_set_id


def test_chunk_preserves_exact_unicode_slice_and_stable_identity()->None:
	version=make_version()
	chunk_set=ChunkSet(version.version_id,SplitterConfig())
	chunk=KnowledgeChunk.from_version(version,chunk_set,0,8,len(version.content),("RPC超时",))
	assert chunk.content==version.content[chunk.start_offset:chunk.end_offset]
	assert len(chunk.content.encode("utf-8"))>len(chunk.content)
	assert replace(chunk).chunk_id==chunk.chunk_id
	assert replace(chunk,heading_path=("其他标题",)).chunk_id!=chunk.chunk_id
	assert len(chunk.content_hash)==64


@pytest.mark.parametrize("settings",[{"chunk_size":0},{"chunk_size":True},{"chunk_size":1.5},
	{"chunk_overlap":-1},{"chunk_overlap":800},{"chunk_overlap":False},{"algorithm_version":" "}])
def test_splitter_rejects_invalid_settings(settings)->None:
	with pytest.raises(ValueError):
		SplitterConfig(**settings)


@pytest.mark.parametrize("content",[""," \n\t",None])
def test_version_rejects_empty_or_non_text_content(content)->None:
	with pytest.raises(ValueError):
		DocumentVersion("doc","local:doc",content)


def test_document_rejects_missing_provenance()->None:
	with pytest.raises(ValueError):
		KnowledgeDocument("doc","标题"," ")


@pytest.mark.parametrize("start,end",[(-1,3),(3,3),(4,2),(0,1000),(True,3)])
def test_chunk_rejects_out_of_bounds_offsets(start,end)->None:
	version=make_version()
	with pytest.raises(ValueError):
		KnowledgeChunk.from_version(version,ChunkSet(version.version_id,SplitterConfig()),0,start,end)


def test_chunk_rejects_wrong_version_and_oversize_slice()->None:
	version=make_version()
	with pytest.raises(ValueError,match="不属于"):
		KnowledgeChunk.from_version(version,ChunkSet("other-version",SplitterConfig()),0,0,3)
	with pytest.raises(ValueError,match="超过"):
		KnowledgeChunk.from_version(version,ChunkSet(version.version_id,SplitterConfig(chunk_size=3,chunk_overlap=0)),0,0,4)


def test_chunk_rejects_length_mismatch_and_invalid_heading()->None:
	chunk_set=ChunkSet(make_version().version_id,SplitterConfig())
	with pytest.raises(ValueError,match="长度"):
		KnowledgeChunk(chunk_set,0,0,4,"abc")
	with pytest.raises(ValueError,match="heading"):
		KnowledgeChunk(chunk_set,0,0,3,"abc",(" ",))


def test_contracts_are_immutable()->None:
	version=make_version()
	with pytest.raises(FrozenInstanceError):
		version.content="覆盖原文"
