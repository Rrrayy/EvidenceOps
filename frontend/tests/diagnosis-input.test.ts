// 验证无效描述被拦截，同时保留简短错误码及多语言日志。
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { diagnosis_input_error } from "../src/lib/diagnosis-input";
test("标点、符号与空白不能创建诊断",()=>{
	for(const description of [""," \n","?","？？？","...","🔥","\u200b","\u0000"]){
		assert.notEqual(diagnosis_input_error(description),"");
	}
	assert.notEqual(diagnosis_input_error("a".repeat(100001)),"");
});
test("短错误码和故障日志不受最小长度或关键词限制",()=>{
	for(const description of ["OOM","404","崩溃","RPC timeout","خطأ","error: 🔥","a".repeat(100000)]){
		assert.equal(diagnosis_input_error(description),"");
	}
});
