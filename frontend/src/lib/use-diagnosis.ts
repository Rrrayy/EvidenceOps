"use client"; // 此模块管理浏览器观察连接。
import { useCallback,useEffect,useRef,useState } from "react"; // 状态与资源生命周期交给 React。
import { useChat } from "@ai-sdk/react"; // 使用 AI SDK 接收适配后的诊断数据。
import { DefaultChatTransport } from "ai"; // 采用 SDK 正式传输实现。
import { apply_event,empty_run,type RunState } from "./run-state"; // 纯函数合并真实事件。
import { result_schema,terminal_events } from "./contracts"; // 复用后端响应校验。
import { read_sse } from "./sse"; // GET 重连仍使用后端原生 SSE。
import { diagnosis_input_error } from "./diagnosis-input";
const transport=new DefaultChatTransport({ api: "/api/diagnosis" }); // 所有创建请求经过协议适配。
export function use_diagnosis() {
	// 管理一次 Run，历史观察与创建共享状态。
	const [state,set_state]=useState<RunState>(empty_run); // 当前运行档案。
	const state_ref=useRef(state); // 回调始终读取最新游标，避免并发闭包滞后。
	const [error,set_error]=useState(""); // 传输错误与报告失败分别显示。
	const [loading,set_loading]=useState(false); // 历史加载和 GET 观察状态。
	const [cancel_pending,set_cancel_pending]=useState(false); // 取消请求仅是意图。
	const controller=useRef<AbortController|null>(null); // 当前 GET 连接的资源所有权。
	const generation=useRef(0); // 阻止旧请求改写新 Run。
	const retry_count=useRef(0); // 自动恢复最多三次，避免持久化故障无限重试。
	const set_run=useCallback((next: RunState) => {
		state_ref.current=next;
		set_state(next);
	},[]); // 同步更新回调与界面。
	const receive=useCallback(
		(data: unknown) => {
			// 同步验证数据，游标只在成功处理后推进。
			try {
				set_run(apply_event(state_ref.current,data));
			} catch(reason) {
				set_error(reason instanceof Error? reason.message:"事件无法解析");
				throw reason;
			} // 损坏流停止而非静默跳过。
		},
		[set_run]
	); // 保持稳定的数据回调。
	const chat=useChat({
		transport,
		onData: (part) => {
			if(part.type==="data-run-event") {
				receive(part.data);
			}
		},
		onError: (reason) => {
			set_error(reason.message);
			set_run({ ...state_ref.current,connection: "disconnected" });
		},
		onFinish: () => {
			if(!state_ref.current.result) {
				set_run({ ...state_ref.current,connection: "disconnected" });
			}
		}
	}); // SDK 管理 POST 流生命周期。
	const busy=chat.status==="submitted"||chat.status==="streaming"||loading; // 传输进行中时禁止重复创建。
	const active=
		busy||
		Boolean(
			state.run_id&&
			(!state.result||["running","pending"].includes(state.result.status))&&
			state.connection!=="idle"
		); // 已加载的活跃历史同样不得覆盖。
	const reset=useCallback(() => {
		generation.current++;
		retry_count.current=0;
		controller.current?.abort();
		chat.stop();
		chat.setMessages([]);
		set_error("");
		set_loading(false);
		set_cancel_pending(false);
		set_run({ ...empty_run });
	},[chat.stop,chat.setMessages,set_run]); // 清理观察资源，不向后端发送取消。
	const start=useCallback(
		async (text: string,selection?: { connection_id: string; model_id: string; expected_version?: number }) => {
			// 新提交先确认输入，避免 SDK 默认连续会话语义。
			if(active) {
				return;
			} // 运行未确定结束前不重复创建。
			const input_error=diagnosis_input_error(text);
			if(input_error) {
				set_error(input_error);
				return;
			}
			reset();
			set_run({ ...empty_run,connection: "connected" }); // 新 Run 使用独立游标。
			try {
				await chat.sendMessage({ text: text.trim() },{ body: selection });
			} catch { } // 错误由 SDK onError 统一处理。
		},
		[active,reset,set_run,chat.sendMessage]
	); // 固定创建操作。
	const observe=useCallback(
		async (run_id: string,fresh: boolean) => {
			// 历史读取与重连只调用 GET。
			controller.current?.abort(); // 释放之前的观察连接。
			const request_controller=new AbortController();
			controller.current=request_controller; // 为本次操作创建独立取消信号。
			const token=++generation.current; // 标记本次请求身份。
			if(fresh) {
				set_run({ ...empty_run,run_id,connection: "connected" });
			} // 切换档案先清空旧报告，不能把旧结论挂在新 ID 下。
			set_loading(true);
			set_error(""); // 提供明确加载反馈。
			try {
				// 网络、解析与历史缺口均可恢复。
				const response=await fetch(`/api/backend/runs/${encodeURIComponent(run_id)}`,{
					signal: request_controller.signal
				}); // 先确认 Run 身份与实际状态。
				const payload=await response.json(); // 同时处理结构化错误。
				if(!response.ok) {
					if(fresh) {
						set_run({ ...empty_run });
					}
					throw new Error(payload.message??"诊断档案读取失败");
				} // 查不到身份时清空页面而非展示旧报告。
				const result=result_schema.parse(payload); // 统一历史响应格式。
				if(token!==generation.current) {
					return;
				} // 旧请求不得污染当前页面。
				if(fresh) {
					set_run({
						...empty_run,
						run_id,
						result,
						connection: result.status==="running"||result.status==="pending"? "connected":"closed"
					});
				} // 已归档结果仍加载其真实事件。
				const cursor=fresh? 0:state_ref.current.cursor; // 重连从最后成功处理的事件之后开始。
				const stream=await fetch(
					`/api/backend/runs/${encodeURIComponent(run_id)}/events/stream?after=${cursor}`,
					{ signal: request_controller.signal }
				); // GET 不会重新执行模型。
				if(!stream.ok) {
					const problem=await stream.json();
					throw new Error(problem.message??"事件读取失败");
				} // 保留 409 等明确错误。
				if(!stream.body) {
					throw new Error("事件流为空");
				} // 拒绝异常响应。
				for await(const frame of read_sse(stream.body,request_controller.signal)) {
					// 补发历史并持续观察活跃 Run。
					if(token!==generation.current) {
						return;
					} // 隔离过期连接。
					const data=JSON.parse(frame.data);
					receive(data); // 合并后推进本地游标。
					if(terminal_events.has(data.event)||data.event==="stream_failed") {
						break;
					} // 不让终态连接无限重试。
				} // 结束事件观察。
				if(token===generation.current) {
					// 流末尾可能没有新的终止事件。
					const latest=await fetch(`/api/backend/runs/${encodeURIComponent(run_id)}`,{
						signal: request_controller.signal
					}); // 回查业务终态。
					if(!latest.ok) {
						throw new Error("无法确认诊断终态，请重试历史查询");
					} // 不能只凭连接结束宣布成功。
					const final_result=result_schema.parse(await latest.json()); // 验证归档结果。
					const terminal=["succeeded","failed","cancelled"].includes(final_result.status); // 业务状态独立判断。
					set_run({
						...state_ref.current,
						result: final_result,
						connection: terminal? "closed":"disconnected"
					}); // 非终态显示观察中断。
				} // 完成终态确认。
			} catch(reason) {
				if(!request_controller.signal.aborted&&token===generation.current) {
					set_error(reason instanceof Error? reason.message:"连接中断");
					set_run({ ...state_ref.current,connection: "disconnected" });
				}
			} finally {
				// 主动释放不显示错误。
				if(token===generation.current) {
					set_loading(false);
				}
			} // 只关闭本次加载标记。
		},
		[receive,set_run]
	); // 提供稳定的历史操作。
	const cancel=useCallback(async () => {
		// 只有显式按钮发送业务取消。
		const run_id=state_ref.current.run_id;
		if(!run_id) {
			return;
		} // 未取得身份不能取消。
		set_cancel_pending(true);
		set_error(""); // 表达正在请求而非已取消。
		try {
			const response=await fetch(`/api/backend/runs/${encodeURIComponent(run_id)}/cancel`,{ method: "POST" });
			const payload=await response.json();
			if(!response.ok) {
				throw new Error(payload.message??"该诊断已进入终态，请回查状态");
			}
			if(!payload.cancellation_requested) {
				await observe(run_id,false);
			}
		} catch(reason) {
			set_error(reason instanceof Error? reason.message:"取消请求失败");
			set_cancel_pending(false);
		} // 终态竞争以实际历史结果为准。
	},[observe]); // 隔离取消请求逻辑。
	useEffect(() => {
		// 断线后只恢复观察，绝不自动重发创建请求。
		if(
			state.connection!=="disconnected"||
			!state.run_id||
			busy||
			retry_count.current>=3||
			(state.result&&["succeeded","failed","cancelled"].includes(state.result.status))
		) {
			return;
		} // 无可靠身份或已终态不重连。
		const timer=setTimeout(
			() => {
				retry_count.current++;
				void observe(state.run_id!,false);
			},
			1000*2**retry_count.current
		); // 有界指数退避。
		return () => clearTimeout(timer); // 卸载和状态变化清理定时器。
	},[state.connection,state.run_id,state.result,busy,observe]); // 只有状态改变才安排恢复。
	useEffect(
		() => () => {
			generation.current++;
			controller.current?.abort();
		},
		[]
	); // 卸载释放 GET 流。
	return { state,error,busy,active,cancel_pending,start,reset,observe,cancel,set_error }; // 页面只使用有意义的操作。
} // 结束运行管理。
