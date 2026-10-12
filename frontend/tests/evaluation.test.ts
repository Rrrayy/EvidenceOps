// 负责核对评测摘要与实际执行错误的一致性。
import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {evaluation_schema} from "../src/lib/evaluation";
test("执行错误统计不能伪造，也不能漏报实际失败",()=>{
	const report=JSON.parse(readFileSync(new URL("./fixtures/evaluation-mock.json",import.meta.url),"utf8"));
	assert.equal(evaluation_schema.safeParse({...report,summary:{...report.summary,execution_error_count:99}}).success,false);
	const failed={...report,results:report.results.map((item:Record<string,unknown>,index:number)=>index===0?{...item,execution_error:"模型超时"}:item)};
	assert.equal(evaluation_schema.safeParse(failed).success,false);
	assert.equal(evaluation_schema.safeParse({...failed,summary:{...report.summary,execution_error_count:1}}).success,true);
});
