from hashlib import sha256
from types import SimpleNamespace

import pytest

from evidenceops.connectors.local_document import DocumentLoadError,LocalDocumentLoader
from evidenceops.domain.knowledge import DocumentVersion


def test_load_preserves_unicode_newlines_and_source(tmp_path)->None:
	path=tmp_path/"guide.MD"
	raw="  # RPC\r\n检查日志\r\n".encode("utf-8")
	path.write_bytes(raw)
	loaded=LocalDocumentLoader(tmp_path).load("guide.MD",purpose="knowledge")
	assert loaded.content==raw.decode("utf-8")
	assert loaded.source_ref=="guide.MD"
	assert loaded.byte_count==len(raw)
	assert loaded.raw_hash==sha256(raw).hexdigest()
	# 加载结果可供版本层使用，但加载器本身不分配文档身份。
	assert DocumentVersion("rpc-guide",loaded.source_ref,loaded.content).content==loaded.content


def test_bom_changes_file_hash_but_not_content_version(tmp_path)->None:
	raw="检查重试".encode("utf-8")
	(tmp_path/"plain.txt").write_bytes(raw)
	(tmp_path/"bom.txt").write_bytes(b"\xef\xbb\xbf"+raw)
	loader=LocalDocumentLoader(tmp_path)
	plain=loader.load("plain.txt",purpose="knowledge")
	bom=loader.load("bom.txt",purpose="knowledge")
	assert plain.content==bom.content
	assert plain.raw_hash!=bom.raw_hash
	assert DocumentVersion("guide",plain.source_ref,plain.content).version_id==DocumentVersion("guide",bom.source_ref,bom.content).version_id


@pytest.mark.parametrize("raw,code",[(b"","EMPTY_DOCUMENT"),(b" \r\n\t","EMPTY_DOCUMENT"),
	(b"\xef\xbb\xbf","EMPTY_DOCUMENT"),(b"\xff","INVALID_ENCODING")])
def test_rejects_empty_or_invalid_text(tmp_path,raw,code)->None:
	(tmp_path/"guide.txt").write_bytes(raw)
	with pytest.raises(DocumentLoadError) as captured:
		LocalDocumentLoader(tmp_path).load("guide.txt",purpose="knowledge")
	assert captured.value.code==code


def test_byte_limit_allows_exact_boundary_and_rejects_larger_file(tmp_path)->None:
	(tmp_path/"guide.txt").write_bytes("中文".encode("utf-8"))
	assert LocalDocumentLoader(tmp_path,6).load("guide.txt",purpose="knowledge").byte_count==6
	with pytest.raises(DocumentLoadError) as captured:
		LocalDocumentLoader(tmp_path,5).load("guide.txt",purpose="knowledge")
	assert captured.value.code=="DOCUMENT_TOO_LARGE"


def test_bounded_read_rejects_growth_after_size_check(tmp_path,monkeypatch)->None:
	from evidenceops.connectors import local_document
	(tmp_path/"guide.txt").write_bytes(b"a"*100)
	original_fstat=local_document.os.fstat
	def stale_size(file_number):
		return SimpleNamespace(st_mode=original_fstat(file_number).st_mode,st_size=1)
	monkeypatch.setattr(local_document.os,"fstat",stale_size)
	with pytest.raises(DocumentLoadError) as captured:
		LocalDocumentLoader(tmp_path,10).load("guide.txt",purpose="knowledge")
	assert captured.value.code=="DOCUMENT_TOO_LARGE"


@pytest.mark.parametrize("relative_path,code",[("","INVALID_PATH"),("../outside.txt","OUTSIDE_ROOT"),
	("missing.txt","DOCUMENT_READ_FAILED"),("guide.json","UNSUPPORTED_FORMAT"),("folder.md","NOT_REGULAR_FILE")])
def test_rejects_invalid_sources(tmp_path,relative_path,code)->None:
	root=tmp_path/"knowledge"
	root.mkdir()
	(tmp_path/"outside.txt").write_text("outside",encoding="utf-8")
	(root/"guide.json").write_text("{}",encoding="utf-8")
	(root/"folder.md").mkdir()
	with pytest.raises(DocumentLoadError) as captured:
		LocalDocumentLoader(root).load(relative_path,purpose="knowledge")
	assert captured.value.code==code


def test_rejects_absolute_paths_and_log_purpose(tmp_path)->None:
	(tmp_path/"guide.txt").write_text("知识",encoding="utf-8")
	loader=LocalDocumentLoader(tmp_path)
	with pytest.raises(DocumentLoadError,match="相对路径"):
		loader.load(str(tmp_path/"guide.txt"),purpose="knowledge")
	with pytest.raises(DocumentLoadError) as captured:
		loader.load("guide.txt",purpose="log")
	assert captured.value.code=="INVALID_PURPOSE"
	with pytest.raises(TypeError):
		loader.load("guide.txt")


@pytest.mark.parametrize("limit",[0,-1,True,1.5])
def test_rejects_invalid_limits(tmp_path,limit)->None:
	with pytest.raises(ValueError):
		LocalDocumentLoader(tmp_path,limit)


def test_rejects_missing_root(tmp_path)->None:
	with pytest.raises(DocumentLoadError) as captured:
		LocalDocumentLoader(tmp_path/"missing")
	assert captured.value.code=="INVALID_ROOT"


def test_resolved_link_cannot_escape_root(tmp_path)->None:
	root=tmp_path/"knowledge"
	root.mkdir()
	outside=tmp_path/"outside.txt"
	outside.write_text("outside",encoding="utf-8")
	try:
		(root/"link.txt").symlink_to(outside)
	except OSError:
		pytest.skip("当前Windows账户没有创建符号链接的权限")
	with pytest.raises(DocumentLoadError) as captured:
		LocalDocumentLoader(root).load("link.txt",purpose="knowledge")
	assert captured.value.code=="OUTSIDE_ROOT"
