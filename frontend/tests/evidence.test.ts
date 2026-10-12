// 验证历史响应重新排序后，引用与详情仍使用相同证据编号。
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { evidence_number } from "../src/lib/evidence";
import type { Evidence } from "../src/lib/contracts";
test("证据编号不受历史返回顺序影响，缺失证据不伪造编号",()=>{
	const items=[{evidence_id:"run-log"},{evidence_id:"run-config"},{evidence_id:"run-metric"}] as Evidence[];
	for(const item of items){assert.equal(evidence_number(items,item.evidence_id),evidence_number([...items].reverse(),item.evidence_id));}
	assert.equal(evidence_number(items,"missing"),"未记录");
});
