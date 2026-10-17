import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from evidenceops.connectors.parsed_log import ParsedLogAdapter,ParsedLogSource,build_parsed_log_tool
from evidenceops.application.agent_diagnosis_factory import build_agent_diagnosis_assembly
from evidenceops.application.model_protocol import ToolCall,StructuredFinalAnswer
from evidenceops.application.diagnosis_history import load_diagnosis_history
from evidenceops.application.history_response import history_response
from evidenceops.application.run_control import RunControl,RunCancelled
from evidenceops.infrastructure.providers.mock_provider import MockProvider
from evidenceops.infrastructure.database.models import Base
from evidenceops.infrastructure.database.diagnosis_persistence import SqlAlchemyDiagnosisPersistence

BINARY=Path(__file__).resolve().parents[1]/'cpp/log_evidence_engine/build-cxx20/log_evidence_cli.exe'

def adapter(tmp_path,command=None,**options):
	path=tmp_path/'rpc.log'
	path.write_text('async rpc completed, errcode=0\n',encoding='utf-8')
	return ParsedLogAdapter(command or (BINARY,),{'rpc':ParsedLogSource('rpc',path,'client')},**options)

@pytest.mark.skipif(not BINARY.exists(),reason='build C++20 CLI first')
def test_agent_archives_exact_model_snapshot(tmp_path):
	engine=create_engine('sqlite:///'+str(tmp_path/'history.sqlite'))
	Base.metadata.create_all(engine)
	persistence=SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)
	parser=adapter(tmp_path)
	seen=[]
	def final(request):
		payload=json.loads(request.messages[-1]['content'])
		seen.append(payload['data']['content'])
		assert payload['data']['metadata']['observed_at_basis']=='import_time'
		return StructuredFinalAnswer({'root_cause':{'text':'当前输入未显示明确失败','evidence_ids':[payload['evidence_id']]},'recommendations':[{'text':'补充受控失败样本','evidence_ids':[payload['evidence_id']]}],'confidence':0.2,'limitations':'仅为正常基线，未知事件时间不能猜测'})
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall('log','query_parsed_logs',{'source_id':'rpc'}),final)),'mock',(build_parsed_log_tool(parser),),'rpc',diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute('test','检查RPC日志')
		assert result.run.status.value=='succeeded'
		assert result.evidences[0].content_snapshot==seen[0]
		parser.sources['rpc'].path.write_text('changed',encoding='utf-8')
		saved=history_response(load_diagnosis_history(persistence,result.run.run_id))
		assert saved['evidences'][0]['content_snapshot']==seen[0]
		assert json.loads(seen[0])['events'][0]['attributes']['errcode']==0
	finally: assembly.close()

@pytest.mark.parametrize('arguments',[{'source_id':'missing'},{'source_id':'rpc','path':'secret'},{'source_id':'rpc','limit':True}])
def test_reject_arbitrary_sources(tmp_path,arguments):
	with pytest.raises(ValueError): build_parsed_log_tool(adapter(tmp_path)).validate_arguments(arguments)

@pytest.mark.parametrize('program,error',[('import time;time.sleep(3)',TimeoutError),('print("bad json")',ValueError),('import sys;sys.stdout.write("x"*10000)',RuntimeError),('import sys;sys.stderr.write("x"*10000)',RuntimeError),('import sys;sys.exit(1)',RuntimeError)])
def test_process_failures(tmp_path,program,error):
	parser=adapter(tmp_path,(sys.executable,'-c',program),timeout=0.2,max_output=2048,max_stderr=1024)
	with pytest.raises(error): parser.query({'source_id':'rpc','limit':10})

def test_cancel_before_spawn(tmp_path):
	control=RunControl()
	control.request_cancel()
	with pytest.raises(RunCancelled): adapter(tmp_path).query({'source_id':'rpc','limit':10},control)

def test_cancel_running_process(tmp_path):
	from threading import Timer
	control=RunControl()
	parser=adapter(tmp_path,(sys.executable,'-c','import time;time.sleep(5)'),timeout=2)
	timer=Timer(0.1,control.request_cancel)
	timer.start()
	try:
		with pytest.raises(RunCancelled): parser.query({'source_id':'rpc','limit':10},control)
	finally: timer.join()

@pytest.mark.skipif(not BINARY.exists(),reason='build C++20 CLI first')
def test_configuration_registers_tool(tmp_path,monkeypatch):
	from evidenceops.connectors.parsed_log import configured_parsed_log_tools
	parser=adapter(tmp_path)
	manifest=tmp_path/'sources.json'
	manifest.write_text(json.dumps([{'source_id':'rpc','path':str(parser.sources['rpc'].path),'role':'client'}]),encoding='utf-8')
	monkeypatch.setenv('EVIDENCEOPS_LOG_SOURCES_FILE',str(manifest))
	monkeypatch.setenv('EVIDENCEOPS_LOG_PARSER_BINARY',str(BINARY))
	tools=configured_parsed_log_tools()
	assert tools[0].name=='query_parsed_logs'
	assert tools[0].parameters_schema['properties']['source_id']['enum']==['rpc']

@pytest.mark.skipif(not BINARY.exists(),reason='build C++20 CLI first')
def test_oversized_event_does_not_hide_later_error(tmp_path):
	parser=adapter(tmp_path)
	text='x'*11000
	parser.sources['rpc'].path.write_text(text+'\nERROR connection refused\n',encoding='utf-8')
	result=parser.query({'source_id':'rpc','limit':10})
	assert [event['raw_text'] for event in result['events']]==['ERROR connection refused']
	assert result['selection']['oversized_count']==1
	assert result['selection']['remaining_budget_count']==0
	assert result['selection']['omitted_count']==1
	assert result['events'][0]['line_start']==2

@pytest.mark.skipif(not BINARY.exists(),reason='build C++20 CLI first')
def test_remaining_budget_skips_whole_event_then_selects_short_event(tmp_path):
	parser=adapter(tmp_path)
	parser.sources['rpc'].path.write_text('a'*2800+'\n'+'b'*2800+'\nERROR connection refused\n',encoding='utf-8')
	result=parser.query({'source_id':'rpc','limit':10})
	assert [event['line_start'] for event in result['events']]==[1,3]
	assert result['selection']['remaining_budget_count']==1
	assert result['selection']['oversized_count']==0
	assert result['events'][0]['raw_text']=='a'*2800

@pytest.mark.skipif(not BINARY.exists(),reason='build C++20 CLI first')
def test_after_line_reaches_tail_without_guessing_keyword(tmp_path):
	parser=adapter(tmp_path)
	path=parser.sources['rpc'].path
	path.write_text(('async rpc completed, errcode=0\n'*11)+'ERROR connection refused\n',encoding='utf-8')
	tool=build_parsed_log_tool(parser)
	first=parser.query(tool.validate_arguments({'source_id':'rpc'}))
	assert len(first['events'])==10 and first['selection']['next_after_line']==10
	second=parser.query(tool.validate_arguments({'source_id':'rpc','after_line':first['selection']['next_after_line']}))
	assert second['events'][-1]['raw_text']=='ERROR connection refused'
	assert second['events'][-1]['line_start']==12
	assert second['selection']['next_after_line'] is None
	assert first['input_sha256']==second['input_sha256']
	path.write_text('changed source\n',encoding='utf-8')
	changed=parser.query(tool.validate_arguments({'source_id':'rpc','after_line':10}))
	assert changed['input_sha256']!=first['input_sha256']
	assert not changed['events'] and 'per_call' in changed['selection']['snapshot_scope']
	for after_line in (-1,True,1.5,2**53):
		with pytest.raises(ValueError): tool.validate_arguments({'source_id':'rpc','after_line':after_line})

@pytest.mark.skipif(not BINARY.exists(),reason='build C++20 CLI first')
def test_cli_stop_reason_codes_and_adapter_partial(tmp_path):
	import subprocess
	parser=adapter(tmp_path)
	path=parser.sources['rpc'].path
	for text,options,reason in [('a\nbbb\n',['--max-input-bytes','3'],'input_limit'),('abc\n',['--max-line-bytes','2'],'line_limit')]:
		path.write_text(text,encoding='utf-8')
		process=subprocess.run([str(BINARY),'--input',str(path),'--source-id','rpc','--role','client',*options],capture_output=True,timeout=5)
		assert process.returncode==2
		document=json.loads(process.stdout)
		assert document['statistics']['stop_reason']==reason and document['error']
	path.write_text('x'*262145+'\n',encoding='utf-8')
	result=parser.query({'source_id':'rpc','limit':10})
	assert result['parser_status']=='partial' and result['statistics']['stop_reason']=='line_limit'
	path.write_bytes(b'x'*(parser.max_input+1))
	with pytest.raises(ValueError,match='adapter byte limit'): parser.query({'source_id':'rpc','limit':10})

@pytest.mark.skipif(not BINARY.exists(),reason='build C++20 CLI first')
def test_agent_continues_to_tail_and_archives_exact_failure_evidence(tmp_path):
	engine=create_engine('sqlite:///'+str(tmp_path/'tail.sqlite'))
	Base.metadata.create_all(engine)
	persistence=SqlAlchemyDiagnosisPersistence(sessionmaker(engine),engine)
	parser=adapter(tmp_path)
	parser.sources['rpc'].path.write_text('async rpc completed, errcode=0\n'*11+'ERROR connection refused\n',encoding='utf-8')
	def continue_reading(request):
		content=json.loads(json.loads(request.messages[-1]['content'])['data']['content'])
		assert content['selection']['next_after_line']==10
		return ToolCall('tail','query_parsed_logs',{'source_id':'rpc','after_line':10})
	def answer(request):
		payload=json.loads(request.messages[-1]['content'])
		content=json.loads(payload['data']['content'])
		assert content['events'][-1]['raw_text']=='ERROR connection refused'
		return StructuredFinalAnswer({'root_cause':{'text':'末尾日志记录连接被拒绝；具体原因仍需核对','evidence_ids':[payload['evidence_id']]},'recommendations':[{'text':'核对监听端口和目标地址','evidence_ids':[payload['evidence_id']]}],'confidence':0.3,'limitations':'确定性测试模型，不能证明真实模型诊断质量'})
	assembly=build_agent_diagnosis_assembly(MockProvider((ToolCall('first','query_parsed_logs',{'source_id':'rpc'}),continue_reading,answer)),'mock',(build_parsed_log_tool(parser),),'rpc',diagnosis_persistence=persistence)
	try:
		result=assembly.diagnosis_service.execute('tail-check','检查日志末尾的连接失败')
		assert result.run.status.value=='succeeded' and len(result.evidences)==2
		parser.sources['rpc'].path.write_text('source changed\n',encoding='utf-8')
		history=history_response(load_diagnosis_history(persistence,result.run.run_id))
		assert history['evidences'][-1]['content_snapshot']==result.evidences[-1].content_snapshot
		assert json.loads(history['evidences'][-1]['content_snapshot'])['events'][-1]['line_start']==12
	finally: assembly.close()
