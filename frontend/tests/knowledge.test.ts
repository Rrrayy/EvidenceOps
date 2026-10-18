// 验证知识快照、失败说明及不可信正文在历史和 SSE 中保持一致。
import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { result_schema,evidence_schema,tool_labels } from "../src/lib/contracts";
import { apply_event,empty_run } from "../src/lib/run-state";
import { KnowledgeEvidence } from "../src/components/knowledge-evidence";
import { Report } from "../src/components/report";

const timestamp="2026-10-15T01:00:00Z";
const evidence={evidence_id:"knowledge-1",source:"knowledge",summary:"连接池",observed_at:timestamp,source_ref:"knowledge:chunk-1",content_hash:"hash",source_version:"v1",content_snapshot:'<script>alert("unsafe")</script>\n中文😀原文',source_metadata:{document_id:"manual",source_ref:"manual.md",heading_path:["手册","连接池"],chunk_id:"chunk-1",chunk_set_id:"chunks-1",embedding_set_id:"embeddings-1",config_fingerprint:"config-1",start_offset:0,end_offset:50,score:0,rank:1,retrieval_method:"cosine"}};
const payload={run_id:"run-knowledge",request_id:"req",status:"failed",error_code:"EVIDENCE_INSUFFICIENT",error_detail:{code:"EVIDENCE_INSUFFICIENT",message:"缺少现场观测",missing_information:["完整错误栈","复现步骤及版本"]},created_at:timestamp,started_at:timestamp,finished_at:timestamp,evidences:[evidence,{...evidence,evidence_id:"knowledge-2"}],report:null,execution_records:[]};

test("历史与终止 SSE 保留多个片段及待补信息，不按工具调用合并",()=>{
	const history=result_schema.parse(payload);
	const state=apply_event(empty_run,{event:"run_failed",sequence:1,run_id:payload.run_id,occurred_at:timestamp,data:{result:payload}});
	assert.deepEqual(state.result,history);
	assert.equal(history.evidences.length,2);
	assert.equal(history.evidences[0].content_snapshot,evidence.content_snapshot);
	assert.deepEqual(history.error_detail?.missing_information,payload.error_detail.missing_information);
	assert.equal(state.connection,"closed");
	assert.equal(tool_labels.search_knowledge,"检索知识资料");
});

test("旧证据和旧错误缺少新增字段仍然兼容",()=>{
	const {content_snapshot,source_metadata,...legacy}=evidence;
	assert.equal(evidence_schema.parse(legacy).content_snapshot,undefined);
	for(const error_detail of [undefined,null,{code:"MODEL_PROTOCOL_ERROR",message:"协议错误"}]){
		assert.equal(result_schema.safeParse({...payload,error_detail,evidences:[legacy]}).success,true);
	}
});

test("知识原文按纯文本转义，零分数不丢失，缺失标题和原文有明确提示",()=>{
	const markup=renderToStaticMarkup(createElement(KnowledgeEvidence,{evidence:evidence_schema.parse(evidence)}));
	assert.ok(markup.includes("&lt;script&gt;"));
	assert.ok(!markup.includes("<script>"));
	assert.ok(!markup.includes("href="));
	assert.ok(markup.includes("0（不是准确率或置信度）"));
	assert.ok(markup.includes("中文😀原文"));
	const missing=renderToStaticMarkup(createElement(KnowledgeEvidence,{evidence:{...evidence_schema.parse(evidence),content_snapshot:null,source_metadata:null}}));
	assert.ok(missing.includes("知识片段"));
	assert.ok(missing.includes("本次运行未记录片段原文"));
});

test("混合检索审计保留分路信息且不把分数包装成置信度",()=>{
	const parsed=result_schema.parse({...payload,evidences:[{...evidence,source_metadata:{...evidence.source_metadata,retrieval_method:"hybrid-rrf-bm25-v1",retrieval_details:{score_kind:"rrf",vector_candidates:10,bm25_candidates:8,branches:{vector:{rank:2,score:0.7},bm25:{rank:1,score:3.2}}}}}]});
	const markup=renderToStaticMarkup(createElement(KnowledgeEvidence,{evidence:parsed.evidences[0]}));
	assert.ok(markup.includes("检索审计"));
	assert.ok(markup.includes("BM25 候选"));
	assert.ok(markup.includes("vector"));
	assert.ok(markup.includes("不是准确率或置信度"));
});

test("证据不足显示补充清单，普通协议错误和取消不会冒充证据不足或成功报告",()=>{
	const render=(input:unknown)=>renderToStaticMarkup(createElement(Report,{result:result_schema.parse(input),on_evidence:()=>{}}));
	const markup=render(payload);
	assert.ok(markup.includes("证据不足，需补充信息"));
	assert.ok(markup.includes("完整错误栈"));
	assert.ok(markup.includes("不代表已确认"));
	for(const status of ["failed","cancelled"]){
		const output=render({...payload,status,error_code:"MODEL_PROTOCOL_ERROR",error_detail:{code:"MODEL_PROTOCOL_ERROR",message:"协议错误"},report:{root_cause:{text:"不应显示的结论",evidence_ids:[]},recommendations:[],confidence:1,limitations:""}});
		assert.ok(output.includes("协议错误"));
		assert.ok(!output.includes("证据不足，需补充信息"));
		assert.ok(!output.includes("不应显示的结论"));
	}
});
