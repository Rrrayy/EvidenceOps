// 验证日志快照安全降级、扫描边界、时间语义与归档一致性。
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { evidence_schema,capability_schema } from "../src/lib/contracts";
import { read_parsed_log,event_time,log_attribute } from "../src/lib/parsed-logs";
import { ParsedLogEvidence } from "../src/components/parsed-log-evidence";
const event={event_index:1,line_start:7,line_end:7,raw_text:'<script>window.injected=true</script> 中文😀',raw_time:"1017 12:30",timestamp:null,format:"unknown",level:"unknown",message:"待识别",warnings:["header_unknown"],code_file:"server.cc",code_line:99};
const snapshot={schema_version:"log-evidence-v1",source_id:"rpc",source_role:"server",parser_status:"partial",events:[event],statistics:{event_count:3,unrecognized_count:1,warning_count:1,stop_reason:"event_limit",stopped_early:true},selection:{rule:"input_order",keyword:null,limit:10,selected_count:1,omitted_count:2},input_sha256:"input-hash",hash_basis:"full_adapter_input_snapshot_bytes",imported_at:"2026-10-17T08:00:00Z"};
const evidence=evidence_schema.parse({evidence_id:"log-1",source:"log",summary:"日志组",observed_at:snapshot.imported_at,source_ref:"parsed-log:rpc",content_hash:"snapshot-hash",source_version:"log-evidence-v1",content_snapshot:JSON.stringify(snapshot),source_metadata:{observed_at_basis:"import_time",source_id:"rpc",input_sha256:"input-hash",line_ranges:[[7,7]],selection:snapshot.selection}});
const render=(value=evidence)=>renderToStaticMarkup(createElement(ParsedLogEvidence,{evidence:value}));
test("真实 CLI 经 Adapter 输出的快照可显示；原文、零值与大整数不伪造",()=>{
	const content_snapshot=readFileSync(new URL("./fixtures/parsed-log-snapshot.json",import.meta.url),"utf8");
	const parsed=read_parsed_log({...evidence,content_snapshot});
	assert.equal(parsed?.events.length,3);
	assert.equal(parsed?.events[0].attributes?.errcode,0);
	assert.ok(render({...evidence,content_snapshot}).includes("errcode=0"));
	assert.equal(log_attribute(0),"0");assert.equal(log_attribute(false),"false");
	assert.ok(log_attribute(Number.MAX_SAFE_INTEGER+1).includes("超出安全整数"));
});
test("保留日志来源元数据；能力目录拒绝畸形内容并兼容旧后端",()=>{
	assert.equal(evidence.source_metadata?.observed_at_basis,"import_time");
	assert.deepEqual(evidence.source_metadata?.line_ranges,[[7,7]]);
	assert.equal(capability_schema.safeParse({persistence:true,provider_mode:"mock"}).success,true);
	assert.equal(capability_schema.safeParse({persistence:true,provider_mode:"mock",parsed_log_sources:[{}]}).success,false);
});
test("日志行号与源码位置区分，未知事件时间不能使用导入时间",()=>{
	const markup=render();
	assert.ok(markup.includes("输入行 7"));
	assert.ok(markup.includes("源码位置（非日志行号）"));
	assert.ok(markup.includes("server.cc:99"));
	assert.equal(event_time(event),"事件时间未知 · 原始时间 1017 12:30");
	assert.equal(event_time({...event,timestamp:"2026-10-17T01:02:03Z"}),"2026-10-17T01:02:03Z");
});
test("部分扫描和未选入事件必须明确限制，不把解析提示当根因",()=>{
	const markup=render();
	for(const text of ["扫描不完整","达到事件数量上限","2 条已解析事件未进入","不等同于业务故障"]){assert.ok(markup.includes(text),text);}
});
test("不可信正文安全渲染，空组不能宣称服务无问题",()=>{
	assert.ok(render().includes("&lt;script&gt;"));assert.ok(!render().includes("<script>"));
	const empty={...snapshot,events:[],selection:{...snapshot.selection,selected_count:0,omitted_count:3}};
	assert.ok(render({...evidence,content_snapshot:JSON.stringify(empty)}).includes("不能据此判断服务没有问题"));
});
test("畸形、缺失、版本不符或计数不一致的快照保留原文，不导致历史整体失败",()=>{
	for(const content_snapshot of [null,"<img onerror=alert(1)>","{}",JSON.stringify({...snapshot,schema_version:"v2"}),JSON.stringify({...snapshot,events:[]})]){
		const value={...evidence,content_snapshot};assert.equal(read_parsed_log(value),null);assert.ok(render(value).includes(content_snapshot==null?"未记录日志正文":"无法识别"));
	}
});
