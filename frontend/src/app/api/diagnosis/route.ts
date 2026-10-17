import { createUIMessageStream,createUIMessageStreamResponse } from "ai"; // 使用 AI SDK 的正式 UI 流协议。
import { backend_fetch,backend_error } from "@/lib/backend"; // 复用现有诊断后端。
import { event_schema,terminal_events } from "@/lib/contracts"; // 只映射真实业务事件。
import { read_sse } from "@/lib/sse"; // 解析跨包 SSE。
import { diagnosis_input_error } from "@/lib/diagnosis-input";
export const runtime="nodejs"; // 流式代理运行在 Node 服务中。
export async function POST(request: Request) {
	// 每次提交只创建一次后端诊断。
	try {
		// 输入与网络错误输出稳定信息。
		const body=await request.json(); // 读取 AI SDK 发来的 UI 消息。
		const last_message=body.messages?.at(-1); // 单次诊断只取最后一条用户输入。
		const description=
			last_message?.role==="user"
				? last_message.parts
					?.filter((part: { type: string }) => part.type==="text")
					.map((part: { text: string }) => part.text)
					.join("\n")
					.trim()
				:""; // 不把旧 Run 对话送给新诊断。
		const input_error=diagnosis_input_error(description??"");
		if(input_error) {
			return Response.json({ message: input_error },{ status: 422 });
		} // 提供明确输入上限。
		const response=await backend_fetch("diagnosis/stream",{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				description,
				connection_id: typeof body.connection_id==="string"? body.connection_id:undefined,
				model_id: typeof body.model_id==="string"? body.model_id:undefined,
				expected_version: Number.isInteger(body.expected_version)? body.expected_version:undefined
			}),
			signal: request.signal
		}); // 取消网络观察不调用业务 cancel。
		if(!response.ok) {
			return Response.json({ message: await backend_error(response) },{ status: response.status });
		} // 保留 429 等状态。
		if(!response.body) {
			return Response.json({ message: "后端未提供诊断事件流" },{ status: 502 });
		} // 拒绝空流。
		const stream=createUIMessageStream({
			execute: async ({ writer }) => {
				// 将现有业务事件转换为自定义数据部分。
				for await(const frame of read_sse(response.body!,request.signal)) {
					// 不依赖网络片段边界。
					const item=event_schema.parse(JSON.parse(frame.data)); // 验证后端信封。
					writer.write({ type: "data-run-event",data: item,transient: true }); // 客户端以此驱动档案和时间线。
					if(terminal_events.has(item.event)||item.event==="stream_failed") {
						break;
					} // 业务终态或传输失败及时结束观察。
				} // 完成流转发。
			},
			onError: reason=>reason instanceof Error&&reason.message==="事件数据超过读取上限"?"事件数据超过读取上限，已停止观察；请按运行 ID 回查档案。":"诊断连接中断，请按运行 ID 恢复观察"
		}); // 不向浏览器泄露服务端异常。
		return createUIMessageStreamResponse({
			stream,
			headers: { "Cache-Control": "no-cache","X-Accel-Buffering": "no" }
		}); // 按 AI SDK 协议返回。
	} catch {
		return Response.json({ message: "无法连接诊断服务，请确认 FastAPI 已启动" },{ status: 502 });
	} // 未确定 Run ID 时不能自动重发 POST。
} // 结束创建接口。
