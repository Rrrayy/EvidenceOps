// 验证多版本模型快照、用户错误文案及错误历史归属的回归边界。
import test from "node:test";
import assert from "node:assert/strict";
import { history_schema,result_schema } from "../src/lib/contracts";
import { run_error_code_message,run_error_message } from "../src/lib/run-errors";
import { apply_event,empty_run } from "../src/lib/run-state";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Report } from "../src/components/report";
import { Trace } from "../src/components/trace";

const payload={run_id:"run-compatibility",request_id:"req",status:"failed",error_code:"EVIDENCE_INSUFFICIENT",created_at:"2026-10-15T01:00:00Z",started_at:null,finished_at:null,evidences:[],report:null,execution_records:[]};

test("模型快照支持连接管理、后端验收、缺字段和 null，不伪造连接信息",()=>{
	for(const model_config of [undefined,null,{}, {provider:"qianwen-platform",model_id:"qwen3.8-flash",acceptance_case:"outside-react-sse"}, {provider_id:"mock",connection_id:"system",connection_name:"系统连接",model_id:"mock-model",config_version:1}, {provider_id:null,connection_id:null,model_id:null,config_version:null}]){
		const result=result_schema.parse({...payload,model_config});
		assert.equal(result.model_config?.connection_name,model_config?.connection_name);
		assert.equal(result.model_config?.provider,(model_config as {provider?:string})?.provider);
	}
});

test("快照字段缺失可以兼容，但错误类型仍拒绝，不吞掉损坏结果",()=>{
	const invalid=result_schema.safeParse({...payload,model_config:{model_id:{secret:"not-for-ui"}}});
	assert.equal(invalid.success,false);
	if(!invalid.success){
		const message=run_error_message(invalid.error);
		assert.ok(message.includes("格式不兼容"));
		for(const internal of ["invalid_type","model_config","secret","not-for-ui"]){assert.ok(!message.includes(internal));}
	}
	assert.ok(run_error_message(new SyntaxError("Unexpected JSON token")).includes("无法读取"));
	assert.ok(run_error_message(new TypeError("Failed to fetch")).includes("无法连接"));
	assert.equal(run_error_message(new Error("诊断运行不存在")),"诊断运行不存在");
});

test("终止事件名称和结果状态冲突时不能宣布成功",()=>{
	assert.throws(()=>apply_event(empty_run,{event:"run_completed",sequence:1,run_id:payload.run_id,occurred_at:payload.created_at,data:{result:payload}}),/状态不一致/);
});

test("历史空列表合法，null、缺失列表和未知状态必须明确拒绝",()=>{
	assert.equal(history_schema.safeParse({items:[],has_more:false}).success,true);
	for(const invalid of [null,{}, {items:null,has_more:false}, {items:[{...payload,status:"unknown"}],has_more:false}]){
		assert.equal(history_schema.safeParse(invalid).success,false);
	}
});

test("两种快照中的 Mock 都明确展示演示边界",()=>{
	for(const model_config of [{provider:"mock"},{provider_id:"mock"}]){
		const result=result_schema.parse({...payload,status:"succeeded",error_code:null,model_config,report:{root_cause:{text:"演示",evidence_ids:[]},recommendations:[],confidence:0.5,limitations:"样例"}});
		const markup=renderToStaticMarkup(createElement(Report,{result,on_evidence:()=>{}}));
		assert.ok(markup.includes("Mock 演示报告"));
		assert.ok(markup.includes("不是针对输入的真实故障结论"));
	}
});

test("Token 配置与执行计量缺失保持可区分，不把未知显示为零",()=>{
	const result=result_schema.parse({...payload,model_config:{provider_id:"qianwen-platform",model_id:"qwen",context_window_tokens:32768,max_output_tokens:2048,max_run_tokens:16384,limits_source:"legacy_compatibility"},execution_records:[{kind:"model",model_round:1,model_request_id:"req-1",tool_name:null,tool_call_id:null,query_arguments:null,started_at:payload.created_at,finished_at:payload.created_at,duration_ms:10,status:"failed",error_code:"CONTEXT_BUDGET_EXCEEDED",estimated_input_tokens:30000,reserved_output_tokens:2048,reported_input_tokens:null,reported_output_tokens:null,reported_total_tokens:null,usage_status:"unknown",payload_hash:null}]});
	assert.equal(result.execution_records[0].reported_total_tokens,null);
	assert.equal(result.model_config?.limits_source,"legacy_compatibility");
	assert.match(run_error_code_message("CONTEXT_BUDGET_EXCEEDED")??"",/未提交给模型服务/);
	assert.match(run_error_code_message("RUN_TOKEN_BUDGET_EXCEEDED")??"",/当前请求未继续提交/);
	const record=result.execution_records[0];
	const trace=renderToStaticMarkup(createElement(Trace,{events:[{event:"model_started",sequence:1,run_id:payload.run_id,occurred_at:payload.created_at,data:{model_request_id:"req-1",model_round:1,model:"qwen"}}],result}));
	assert.ok(trace.includes("Token 记录"));
	assert.ok(trace.includes("30,000"));
	assert.ok(trace.includes("未知"));
	assert.ok(!trace.includes(">0<"));
	const partial=result_schema.parse({...payload,status:"succeeded",error_code:null,report:{root_cause:{text:"根因",evidence_ids:[]},recommendations:[],confidence:0.5,limitations:"边界"},execution_records:[{...record,estimated_input_tokens:null,reserved_output_tokens:null,reported_input_tokens:null,reported_output_tokens:17,reported_total_tokens:null,usage_status:null}]});
	const partial_trace=renderToStaticMarkup(createElement(Trace,{events:[{event:"model_started",sequence:1,run_id:payload.run_id,occurred_at:payload.created_at,data:{model_request_id:"req-1",model_round:1,model:"qwen"}}],result:partial}));
	assert.ok(partial_trace.includes("供应商输出"));
	assert.ok(partial_trace.includes("17"));
	assert.ok(partial_trace.includes("供应商总量</dt><dd>未记录"));
	const legacy=result_schema.parse({...payload,status:"succeeded",error_code:null,report:{root_cause:{text:"根因",evidence_ids:[]},recommendations:[],confidence:0.5,limitations:"边界"},execution_records:[{...record,estimated_input_tokens:null,reserved_output_tokens:null,reported_input_tokens:null,reported_output_tokens:null,reported_total_tokens:null,usage_status:null}]});
	const legacy_trace=renderToStaticMarkup(createElement(Trace,{events:[{event:"model_started",sequence:1,run_id:payload.run_id,occurred_at:payload.created_at,data:{model_request_id:"req-1",model_round:1,model:"qwen"}}],result:legacy}));
	assert.ok(!legacy_trace.includes("Token 记录"));
	const budget_result=result_schema.parse({...payload,error_code:"RUN_TOKEN_BUDGET_EXCEEDED",execution_records:[{...record,model_round:1,model_request_id:"req-success",status:"succeeded",error_code:null},{...record,model_round:2,model_request_id:"req-budget",status:"failed",error_code:"RUN_TOKEN_BUDGET_EXCEEDED"}]});
	const report=renderToStaticMarkup(createElement(Report,{result:budget_result,on_evidence:()=>{}}));
	assert.ok(report.includes("此前轮次已有成功调用"));
	assert.ok(!report.includes("本次没有模型成功调用记录"));
	const budget_events=[1,2].map((model_round)=>({event:"model_started",sequence:model_round,run_id:payload.run_id,occurred_at:payload.created_at,data:{model_request_id:model_round===1?"req-success":"req-budget",model_round,model:"qwen"}}));
	const budget_trace=renderToStaticMarkup(createElement(Trace,{events:budget_events,result:budget_result}));
	assert.equal((budget_trace.match(/<details class="trace-item /g)??[]).length,2);
});
