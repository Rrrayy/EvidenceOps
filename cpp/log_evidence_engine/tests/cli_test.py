import json
import pathlib
import subprocess
import sys
import tempfile

binary=str(pathlib.Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='evidenceops-cli-') as directory:
	path=pathlib.Path(directory)/'input.log'
	def run(data,*options,code=0):
		path.write_bytes(data)
		result=subprocess.run([binary,'--input',str(path),'--source-id','test',*options],capture_output=True,timeout=30)
		assert result.returncode==code,(result.returncode,result.stderr)
		document=json.loads(result.stdout)
		assert document['statistics']['event_count']==len(document['events'])
		assert [event['event_index'] for event in document['events']]==list(range(1,len(document['events'])+1))
		return document,result
	assert run(b'abc\r')[0]['events'][0]['raw_text']=='abc\r'
	assert run(b'\xff',code=1)[0]['status']=='failed'
	limited=run(b'ab\ncde\n','--max-input-bytes','5',code=2)[0]
	assert len(limited['events'])==1 and limited['statistics']['stop_reason']=='input_limit'
	assert limited['error']
	limited=run(b'abc\n','--max-line-bytes','2',code=2)[0]
	assert limited['status']=='partial' and limited['statistics']['stop_reason']=='line_limit'
	assert limited['error']
	assert run(b'a\nb\n','--max-events','1',code=2)[0]['statistics']['stop_reason']=='event_limit'
	assert run(b'a\n','--max-events','1')[0]['status']=='complete'
	document,result=run(b'x'*3000,'--max-output-bytes','2000',code=2)
	assert len(result.stdout)<=2000 and document['statistics']['stop_reason']=='output_limit'
	assert len(run(b'async rpc completed, errcode=oops')[0]['events'][0]['warnings'])==3
	run(b'\xef\xbb\xbfhello','--bom','reject',code=1)
	document,_=run(b'19700101 00:00:00.000001Z 5958 INFO  ok - Server.cc:80\n')
	assert document['events'][0]['timestamp']=='1970-01-01T00:00:00.000001Z'
	document,_=run(bytes([34,92,0,10]))
	assert document['events'][0]['raw_text']==chr(34)+chr(92)+chr(0)
	for options,code in [(['--input',str(path.parent/'missing'),'--source-id','test'],1),(['--bad','x'],3),(['--input',str(path),'--source-id','test','--max-output-bytes','1'],1)]:
		result=subprocess.run([binary,*options],capture_output=True,timeout=30)
		assert result.returncode==code and result.stderr
		if result.stdout: assert json.loads(result.stdout)['status']=='failed'
	if len(sys.argv)>2:
		result=subprocess.run([binary,'--input',sys.argv[2],'--source-id','rpc-server','--role','server'],capture_output=True,timeout=30)
		assert result.returncode==0,result.stderr
		document=json.loads(result.stdout)
		assert sum(event['format']=='muduo' for event in document['events'])==220
		assert document['status']=='complete'
print('CLI acceptance passed')
