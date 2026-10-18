import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from evidenceops.application import knowledge_comparison as comparison


def test_cli_saves_audit_without_overwriting(tmp_path,monkeypatch,capsys):
	manifest=tmp_path/'manifest.json'
	cases=tmp_path/'cases.json'
	output=tmp_path/'result.json'
	manifest.write_text(json.dumps({'documents':[{'document_id':'manual','path':'manual.md','title':'Manual'}]}),encoding='utf-8')
	cases.write_text(json.dumps({'cases':[]}),encoding='utf-8')
	case_hash=sha256(cases.read_bytes()).hexdigest()
	disposed=[]
	engine=SimpleNamespace(dispose=lambda:disposed.append(True))
	monkeypatch.setattr(comparison.DatabaseSettings,'from_environment',lambda:None)
	monkeypatch.setattr(comparison,'create_database_engine',lambda settings:engine)
	monkeypatch.setattr(comparison,'create_session_factory',lambda engine:None)
	monkeypatch.setattr(comparison,'configured_embedding_provider',lambda:None)
	def compare(*args):
		# 编码等待期间的文件修改不能改变本次实际使用的案例哈希。
		cases.write_text('changed',encoding='utf-8')
		return {'summary':{'bm25':{}},'results':[]}
	monkeypatch.setattr(comparison,'compare_cases',compare)
	monkeypatch.setattr('sys.argv',['comparison','--manifest',str(manifest),'--cases',str(cases),'--output',str(output)])
	comparison.main()
	saved=json.loads(output.read_text(encoding='utf-8'))
	assert saved['experiment']['cases_sha256']==case_hash
	assert saved['experiment']['started_at']<=saved['experiment']['finished_at']
	assert saved['summary']=={'bm25':{}} and disposed==[True]
	assert json.loads(capsys.readouterr().out)['output']==output.as_posix()
	with pytest.raises(ValueError,match='已存在'): comparison.main()
	assert json.loads(output.read_text(encoding='utf-8'))==saved
	assert disposed==[True]


def test_cli_disposes_engine_when_comparison_fails(tmp_path,monkeypatch):
	manifest=tmp_path/'manifest.json'
	cases=tmp_path/'cases.json'
	output=tmp_path/'result.json'
	manifest.write_text(json.dumps({'documents':[{'document_id':'manual','path':'manual.md','title':'Manual'}]}),encoding='utf-8')
	cases.write_text(json.dumps({'cases':[]}),encoding='utf-8')
	disposed=[]
	monkeypatch.setattr(comparison.DatabaseSettings,'from_environment',lambda:None)
	monkeypatch.setattr(comparison,'create_database_engine',lambda settings:SimpleNamespace(dispose=lambda:disposed.append(True)))
	monkeypatch.setattr(comparison,'create_session_factory',lambda engine:None)
	monkeypatch.setattr(comparison,'configured_embedding_provider',lambda:None)
	def fail(*args): raise RuntimeError('provider failed')
	monkeypatch.setattr(comparison,'compare_cases',fail)
	monkeypatch.setattr('sys.argv',['comparison','--manifest',str(manifest),'--cases',str(cases),'--output',str(output)])
	with pytest.raises(RuntimeError,match='provider failed'): comparison.main()
	assert disposed==[True] and not output.exists()
