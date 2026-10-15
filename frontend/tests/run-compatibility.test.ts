// 验证多版本模型快照、用户错误文案及错误历史归属的回归边界。
import test from "node:test";
import assert from "node:assert/strict";
import { history_schema,result_schema } from "../src/lib/contracts";
import { run_error_message } from "../src/lib/run-errors";
import { apply_event,empty_run } from "../src/lib/run-state";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Report } from "../src/components/report";

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
