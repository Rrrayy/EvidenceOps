import { event_schema,result_schema,terminal_events,type RunEvent,type RunResult } from "./contracts"; // 共享后端契约与终态定义。
export type RunState={
	run_id: string|null;
	cursor: number;
	events: RunEvent[];
	result: RunResult|null;
	connection: "idle"|"connected"|"disconnected"|"closed";
	cancel_requested: boolean;
}; // 独立维护传输状态与业务状态。
export const empty_run: RunState={
	run_id: null,
	cursor: 0,
	events: [],
	result: null,
	connection: "idle",
	cancel_requested: false
}; // 新诊断不继承旧游标。
export function apply_event(state: RunState,input: unknown): RunState {
	// 纯函数便于验证去重、归属与终态行为。
	const item=event_schema.parse(input); // 拒绝损坏的事件信封。
	if(state.run_id&&item.run_id&&state.run_id!==item.run_id) {
		throw new Error("收到其他诊断的事件，已停止观察");
	} // 避免跨 Run 污染。
	if(item.event==="stream_failed") {
		return { ...state,run_id: state.run_id??item.run_id,connection: "disconnected" };
	} // 传输错误不推进游标、不改业务结果。
	if(!item.run_id||item.sequence<1) {
		throw new Error("业务事件缺少有效身份");
	} // 无身份的业务数据不能进入档案。
	if(item.sequence<=state.cursor) {
		return state;
	} // 重连补发去重。
	if(item.sequence!==state.cursor+1) {
		throw new Error("执行事件存在缺口，请重新加载历史");
	} // 不将残缺过程包装为完整。
	if(state.result&&terminal_events.has(state.events.at(-1)?.event??"")) {
		return state;
	} // 已确认终态拒绝迟到业务事件。
	const result=terminal_events.has(item.event)? result_schema.parse(item.data.result):state.result; // 终止事件包含完整归档。
	const terminal_status:Record<string,string>={run_completed:"succeeded",run_failed:"failed",run_cancelled:"cancelled"};
	if(terminal_events.has(item.event)&&result?.status!==terminal_status[item.event]){throw new Error("终止事件与运行状态不一致，请重新读取档案。");}
	if(result&&result.run_id!==item.run_id) {
		throw new Error("报告不属于当前诊断");
	} // 校验终态归属。
	return {
		...state,
		run_id: item.run_id,
		cursor: item.sequence,
		events: [...state.events,item],
		result,
		connection: terminal_events.has(item.event)? "closed":"connected",
		cancel_requested: state.cancel_requested||item.event==="run_cancel_requested"
	}; // 原子更新本次运行视图。
} // 结束事件合并。
