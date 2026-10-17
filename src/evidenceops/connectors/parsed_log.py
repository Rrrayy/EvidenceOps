"""受控来源经过 C++ CLI 校验后，提供有界日志证据组。"""
import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC,datetime
from hashlib import sha256
from pathlib import Path

from evidenceops.application.tool_runtime import ToolSpec


@dataclass(frozen=True,slots=True)
class ParsedLogSource:
	source_id:str
	path:Path
	role:str="unknown"


class ParsedLogAdapter:
	def __init__(self,command,sources,timeout=5,max_input=1048576,max_output=2097152,max_stderr=65536):
		self.command=tuple(str(item) for item in command)
		self.sources=dict(sources)
		self.timeout=timeout
		self.max_input=max_input
		self.max_output=max_output
		self.max_stderr=max_stderr
		if not self.command or not 0<timeout<=30 or min(max_input,max_output,max_stderr)<=0:
			raise ValueError("invalid parser execution limits")
		for identity,source in self.sources.items():
			if identity!=source.source_id or not isinstance(identity,str) or not 1<=len(identity)<=100 or source.role not in ("server","client","unknown"):
				raise ValueError("invalid registered parser source")

	def _execute(self,arguments,control):
		if control is not None: control.check()
		process=subprocess.Popen([*self.command,*arguments],stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,
			creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
		buffers=[bytearray(),bytearray()]
		overflow=threading.Event()
		def drain(stream,index,limit):
			try:
				while True:
					chunk=stream.read(4096)
					if not chunk: break
					remaining=limit-len(buffers[index])
					buffers[index].extend(chunk[:remaining])
					if len(chunk)>remaining:
						overflow.set()
						try: process.kill()
						except ProcessLookupError: pass
						break
			finally: stream.close()
		threads=[threading.Thread(target=drain,args=(stream,index,limit),daemon=True)
			for index,(stream,limit) in enumerate(((process.stdout,self.max_output),(process.stderr,self.max_stderr)))]
		for thread in threads: thread.start()
		deadline=time.monotonic()+self.timeout
		try:
			while process.poll() is None:
				if control is not None: control.check()
				if overflow.is_set(): raise RuntimeError("parser output limit exceeded")
				if time.monotonic()>=deadline: raise TimeoutError("parser execution timed out")
				time.sleep(0.01)
		finally:
			if process.poll() is None: process.kill()
			process.wait()
			for thread in threads: thread.join()
		if control is not None: control.check()
		if overflow.is_set(): raise RuntimeError("parser output limit exceeded")
		if process.returncode not in (0,2): raise RuntimeError("parser failed; input may be unreadable or invalid UTF-8")
		return bytes(buffers[0]),process.returncode

	def query(self,arguments,control=None):
		source=self.sources[arguments["source_id"]]
		if control is not None: control.check()
		with source.path.open("rb") as stream: raw=stream.read(self.max_input+1)
		if len(raw)>self.max_input: raise ValueError("registered input exceeds adapter byte limit")
		with tempfile.TemporaryDirectory(prefix="evidenceops-parser-") as directory:
			path=Path(directory)/"input.log"
			path.write_bytes(raw)
			payload,exit_code=self._execute(["--input",str(path),"--source-id",source.source_id,"--role",source.role,
				"--max-input-bytes",str(self.max_input),"--max-line-bytes","262144","--max-events","10000",
				"--max-output-bytes",str(self.max_output)],control)
		document=validate_document(payload,exit_code,source,raw)
		selected=[]
		after_line=arguments.get("after_line",0)
		last_line=after_line
		oversized_count=0
		remaining_budget_count=0
		stop_reason="end_of_parsed_events"
		for event in document["events"]:
			if event["line_start"]<=after_line: continue
			if len(selected)>=arguments["limit"]:
				stop_reason="selection_limit"
				break
			last_line=event["line_end"]
			if arguments.get("keyword") and arguments["keyword"].casefold() not in event["raw_text"].casefold(): continue
			# 不截断事件；单条超限与剩余预算不足分别记录，继续检查后续短事件。
			if len(json.dumps([event],ensure_ascii=False,allow_nan=False))>10000:
				oversized_count+=1
				continue
			candidate=[*selected,event]
			if len(json.dumps(candidate,ensure_ascii=False,allow_nan=False))>10000:
				remaining_budget_count+=1
				continue
			selected=candidate
		return {"source_id":source.source_id,"source_role":source.role,"schema_version":document["schema_version"],
			"parser_status":document["status"],"statistics":document["statistics"],"events":selected,
			"input_sha256":sha256(raw).hexdigest(),"hash_basis":"full_adapter_input_snapshot_bytes",
			"imported_at":datetime.now(UTC).isoformat(),"selection":{"rule":"input_order_after_line_keyword_skip_over_budget_within_10000_characters",
				"after_line":after_line,"last_examined_line":last_line,"next_after_line":last_line if stop_reason=="selection_limit" else None,
				"stop_reason":stop_reason,"oversized_count":oversized_count,"remaining_budget_count":remaining_budget_count,
				"snapshot_scope":"per_call_input_snapshot; compare input_sha256 before continuing across calls",
				"keyword":arguments.get("keyword"),"limit":arguments["limit"],"selected_count":len(selected),
				"omitted_count":len(document["events"])-len(selected)}}


def validate_document(payload,exit_code,source,raw):
	def unique_object(pairs):
		result={}
		for key,value in pairs:
			if key in result: raise ValueError("duplicate JSON field")
			result[key]=value
		return result
	document=json.loads(payload.decode("utf-8"),object_pairs_hook=unique_object,parse_constant=lambda value:(_ for _ in ()).throw(ValueError("nonfinite JSON")))
	if not isinstance(document,dict) or document.get("schema_version")!="log-evidence-v1": raise ValueError("unsupported parser schema")
	if document.get("status")!=("complete" if exit_code==0 else "partial"): raise ValueError("parser status/exit mismatch")
	identity=document.get("source",{})
	if identity.get("source_id")!=source.source_id or identity.get("source_role")!=source.role: raise ValueError("parser source mismatch")
	events=document.get("events")
	statistics=document.get("statistics")
	if not isinstance(events,list) or len(events)>10000 or not isinstance(statistics,dict): raise ValueError("invalid parser events")
	for field in ("input_bytes","event_count","unrecognized_count","warning_count","skipped_blank_lines"):
		if type(statistics.get(field)) is not int or statistics[field]<0: raise ValueError("invalid parser counters")
	if statistics["event_count"]!=len(events) or statistics["input_bytes"]>len(raw): raise ValueError("inconsistent parser counters")
	if statistics["unrecognized_count"]!=sum(event.get("format")=="unknown" for event in events if isinstance(event,dict)):
		raise ValueError("inconsistent unknown event count")
	if type(statistics.get("stopped_early")) is not bool or statistics["stopped_early"]!=(exit_code==2): raise ValueError("invalid partial status")
	if exit_code==0 and statistics["input_bytes"]!=len(raw): raise ValueError("incomplete scan declared complete")
	lines=raw.decode("utf-8-sig").split("\n")
	previous=0
	for index,event in enumerate(events,1):
		if not isinstance(event,dict) or type(event.get("event_index")) is not int or event["event_index"]!=index: raise ValueError("invalid event identity")
		start,end=event.get("line_start"),event.get("line_end")
		if type(start) is not int or type(end) is not int or start!=end or not previous<start<=len(lines): raise ValueError("invalid event lines")
		expected=lines[start-1]
		if start<len(lines) and expected.endswith("\r"): expected=expected[:-1]
		if event.get("raw_text")!=expected: raise ValueError("event original text mismatch")
		previous=end
		if event.get("format") not in ("glog","zookeeper","muduo","plain","unknown"): raise ValueError("invalid event format")
		for field in ("raw_time","message"):
			if not isinstance(event.get(field),str): raise ValueError("invalid event text")
		if not isinstance(event.get("warnings"),list) or any(not isinstance(item,str) or not item for item in event["warnings"]): raise ValueError("invalid warnings")
		if event.get("time_basis") not in ("unknown","input_timezone","explicit_timezone"): raise ValueError("invalid time basis")
		if event.get("timestamp") is not None:
			timestamp=datetime.fromisoformat(event["timestamp"])
			if timestamp.tzinfo is None or timestamp.utcoffset() is None or event["time_basis"]=="unknown": raise ValueError("invalid event time")
		for field in ("thread_id","code_file","code_function","raw_level","event_kind"):
			if event.get(field) is not None and not isinstance(event[field],str): raise ValueError("invalid optional text")
		for field in ("process_id","code_line"):
			if event.get(field) is not None and (type(event[field]) is not int or not 0<=event[field]<=2**64-1): raise ValueError("invalid numeric field")
		if event.get("level") not in (None,"trace","debug","info","warning","error","fatal","unknown"): raise ValueError("invalid event level")
		if not isinstance(event.get("attributes"),dict) or any(type(value) not in (str,int,bool) for value in event["attributes"].values()): raise ValueError("invalid attributes")
	if statistics["warning_count"]!=sum(len(event["warnings"]) for event in events): raise ValueError("inconsistent warning count")
	return document


def build_parsed_log_tool(adapter):
	def validate(arguments):
		if set(arguments)-{"source_id","keyword","limit","after_line"}: raise ValueError("unknown parser query argument")
		identity=arguments.get("source_id")
		if not isinstance(identity,str) or identity not in adapter.sources: raise ValueError("source_id must be registered")
		limit=arguments.get("limit",10)
		if type(limit) is not int or not 1<=limit<=20: raise ValueError("limit must be 1..20")
		keyword=arguments.get("keyword")
		if keyword is not None and (not isinstance(keyword,str) or not keyword.strip() or len(keyword)>200): raise ValueError("invalid keyword")
		after_line=arguments.get("after_line",0)
		if type(after_line) is not int or not 0<=after_line<=2**53-1: raise ValueError("after_line must be a nonnegative safe integer")
		return {"source_id":identity,"keyword":keyword,"limit":limit,"after_line":after_line}
	return ToolSpec("query_parsed_logs",True,validate,adapter.query,{"type":"object","properties":{
		"source_id":{"type":"string","enum":list(adapter.sources)},"keyword":{"type":"string","maxLength":200},
		"after_line":{"type":"integer","minimum":0,"maximum":2**53-1,"description":"Read events after this original input line. Use selection.next_after_line to continue. Each call rereads the source; compare input_sha256 before combining snapshots. Oversized events are skipped, never truncated."},
		"limit":{"type":"integer","minimum":1,"maximum":20}},"required":["source_id"],"additionalProperties":False},
		controlled_handler=adapter.query,timeout_seconds=adapter.timeout+2)


def configured_parsed_log_tools():
	manifest=os.getenv("EVIDENCEOPS_LOG_SOURCES_FILE")
	if not manifest: return ()
	binary=Path(os.environ["EVIDENCEOPS_LOG_PARSER_BINARY"]).resolve(strict=True)
	path=Path(manifest).resolve(strict=True)
	if path.stat().st_size>65536: raise ValueError("source manifest too large")
	entries=json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(entries,list) or not 1<=len(entries)<=16: raise ValueError("expected 1..16 registered sources")
	sources={}
	for entry in entries:
		source=ParsedLogSource(entry["source_id"],Path(entry["path"]).resolve(strict=True),entry.get("role","unknown"))
		if source.source_id in sources or not source.path.is_file(): raise ValueError("duplicate or invalid source")
		sources[source.source_id]=source
	return (build_parsed_log_tool(ParsedLogAdapter((binary,),sources)),)
