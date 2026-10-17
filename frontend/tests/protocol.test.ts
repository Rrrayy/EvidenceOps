import test from "node:test"; // 使用 Node 内置测试，不添加重型测试框架。
import assert from "node:assert/strict"; // 验证协议行为而非仅快照实现。
import { read_sse } from "../src/lib/sse"; // 测试实际网络解析函数。
import { apply_event,empty_run } from "../src/lib/run-state"; // 验证状态归属与恢复。
import { evaluation_schema } from "../src/lib/evaluation"; // 导入格式的一致性边界。
import { readFileSync } from "node:fs"; // 使用真实评测文件验证兼容性。
test("UTF-8 与 CRLF 在任意单字节分包下仍完整解析",async()=>{ // 覆盖现实网络边界。
	const bytes=new TextEncoder().encode(': heartbeat\r\nevent: run_started\r\nid: run-1:1\r\ndata: {"text":"中文证据"}\r\n\r\n'); // 中文字符和分隔符故意跨包。
	const stream=new ReadableStream<Uint8Array>({start(controller){for(const byte of bytes){controller.enqueue(new Uint8Array([byte]));}controller.close();}}); // 模拟最碎网络分片。
	const frames=[];for await(const frame of read_sse(stream)){frames.push(frame);} // 消费实际解析器。
	assert.equal(frames.length,1);assert.equal(frames[0].id,"run-1:1");assert.equal(JSON.parse(frames[0].data).text,"中文证据"); // 注释不能成为业务事件。
}); // 结束分包测试。
test("多行 SSE 与未完成事件不会误提交",async()=>{ // 防止连接中断时出现半份报告。
	const stream=new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new TextEncoder().encode("data: one\ndata: two\n\ndata: partial"));controller.close();}}); // 尾部缺少事件分隔。
	const frames=[];for await(const frame of read_sse(stream)){frames.push(frame);} // 按协议消费。
	assert.deepEqual(frames.map((frame)=>frame.data),["one\ntwo"]); // 不完整事件被丢弃。
}); // 结束不完整事件测试。
test("CR 单独换行在流末尾正确提交",async()=>{ // 覆盖 SSE 的第三种合法行分隔。
	const stream=new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new TextEncoder().encode("data: complete\r\r"));controller.close();}}); // 流结束时无 LF。
	const frames=[];for await(const frame of read_sse(stream)){frames.push(frame);} // 使用正式解析器。
	assert.equal(frames[0].data,"complete"); // 合法事件不能丢失。
}); // 结束 CR 测试。
const started={event:"run_started",run_id:"run-1",sequence:1,occurred_at:"2026-10-12T00:00:00Z",data:{status:"running"}}; // 与真实业务信封一致。
test("SSE 累计帧、已完成长行和未完成行均受预算限制，超限取消且不推进游标",async()=>{
	for(const payload of ["data: "+"x".repeat(4_000_001)+"\n\n",("data: "+"x".repeat(1_000_000)+"\n").repeat(5)+"\n","data: "+"x".repeat(4_000_001),("data: "+"x".repeat(1_000_000)+"\n").repeat(3)+"data: "+"x".repeat(1_000_000)]){
		let cancelled=false;
		let state=apply_event(empty_run,started);
		let sent=false;
		const stream=new ReadableStream<Uint8Array>({pull(controller){if(!sent){sent=true;controller.enqueue(new TextEncoder().encode(payload));}},cancel(){cancelled=true;}});
		await assert.rejects(async()=>{for await(const frame of read_sse(stream)){state=apply_event(state,JSON.parse(frame.data));}},/超过读取上限/);
		assert.equal(cancelled,true);assert.equal(stream.locked,false);assert.equal(state.cursor,1);
	}
});
test("SSE 多帧单包分别计预算，跨包累计也不能绕过上限",async()=>{
	const payload="data: "+"x".repeat(2_100_000)+"\n\n";
	const stream=new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new TextEncoder().encode(payload.repeat(2)));controller.close();}});
	let count=0;for await(const frame of read_sse(stream)){assert.equal(frame.data.length,2_100_000);count++;}assert.equal(count,2);
	const multiline="data: "+"x".repeat(900_000)+"\n";
	const fragmented=new ReadableStream<Uint8Array>({start(controller){for(let index=0;index<5;index++){controller.enqueue(new TextEncoder().encode(multiline));}controller.close();}});
	await assert.rejects(async()=>{for await(const frame of read_sse(fragmented)){assert.fail("超限帧不应交付");}},/超过读取上限/);
});
test("重放去重、跨 Run 拒绝与缺口检测",()=>{ // 保护历史链完整性。
	const state=apply_event(empty_run,started);assert.equal(apply_event(state,started),state); // 重复事件不重复显示。
	assert.throws(()=>apply_event(state,{...started,run_id:"run-2",sequence:2}),/其他诊断/); // 其他 Run 不得合并。
	assert.throws(()=>apply_event(state,{...started,sequence:3}),/缺口/); // 游标不能跳号。
}); // 结束重连状态测试。
test("stream_failed 不推进游标也不伪造业务失败",()=>{ // 将传输状态和任务状态区分。
	const state=apply_event(empty_run,started);const next=apply_event(state,{...started,event:"stream_failed",sequence:99}); // 无持久化身份的错误。
	assert.equal(next.cursor,1);assert.equal(next.result,null);assert.equal(next.connection,"disconnected");assert.equal(next.events.length,1); // 允许按可靠游标重连。
}); // 结束传输错误测试。
test("终止报告必须属于本次 Run",()=>{ // 防止错误报告身份。
	const result={run_id:"other",request_id:"req",status:"succeeded",error_code:null,created_at:started.occurred_at,started_at:started.occurred_at,finished_at:started.occurred_at,evidences:[],report:null,execution_records:[]}; // 格式合法但归属错误。
	assert.throws(()=>apply_event(apply_event(empty_run,started),{...started,event:"run_completed",sequence:2,data:{result}}),/不属于/); // 业务归属校验必须拒绝。
}); // 结束归属测试。
test("真实评测文件可读取且伪造统计被拒绝",()=>{ // 规则通过率不能冒充语义准确率。
	const report=JSON.parse(readFileSync(new URL("./fixtures/evaluation-mock.json",import.meta.url),"utf8")); // 使用仓库真实格式。
	assert.equal(evaluation_schema.parse(report).summary.case_count,20); // 确认兼容。
	assert.equal(evaluation_schema.safeParse({...report,summary:{...report.summary,rule_passed_count:19}}).success,false); // 摘要必须与案例一致。
}); // 结束评测验证。
