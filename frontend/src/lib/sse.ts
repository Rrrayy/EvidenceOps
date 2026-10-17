export type SseFrame={ event: string; id: string|null; data: string }; // 保留服务器原始身份，禁止把传输错误当成游标。
export async function* read_sse(stream: ReadableStream<Uint8Array>,signal?: AbortSignal): AsyncGenerator<SseFrame> {
	// 跨网络分块解析 SSE。
	const reader=stream.getReader(); // 独占流读取器并在结束时释放。
	const decoder=new TextDecoder(); // 流式解码避免拆开的中文字符损坏。
	let buffer=""; // 保存尚未组成一整行的字节文本。
	let event_name="message"; // SSE 默认事件名。
	let event_id: string|null=null; // 每帧重新记录业务身份。
	let frame_size=0;
	let data_lines: string[]=[]; // 合并合法的多行 data 字段。
	try {
		// 任何解析错误也必须释放读取器。
		while(true) {
			// 逐块处理，不能假设网络包等于事件。
			if(signal?.aborted) {
				throw new DOMException("已停止观察","AbortError");
			} // 遵守调用者的观察取消。
			const chunk=await reader.read(); // 等待一个网络片段。
			buffer+=decoder.decode(chunk.value,{ stream: !chunk.done }); // 保留跨包字符解码状态。
			if(chunk.done&&buffer.endsWith("\r")) {
				buffer+="\n";
			} // 流末尾的 CR 是合法行结束符，不等待不存在的下一包。
			let match: RegExpExecArray|null; // 记录一条完整行的结束位置。
			while((match=/\r\n|\n|\r(?!$)/.exec(buffer))!==null) {
				// 接受 LF、CRLF 与 CR，末尾 CR 等下一包。
				if(match.index>4_000_000){throw new Error("事件数据超过读取上限");}
				const line=buffer.slice(0,match.index); // 截取一整行。
				buffer=buffer.slice(match.index+match[0].length); // 移除已消费部分。
				if(line==="") {
					// 空行提交完整事件。
					if(data_lines.length) {
						yield { event: event_name,id: event_id,data: data_lines.join("\n") };
					} // 心跳注释不产生业务事件。
					event_name="message";
					event_id=null;
					data_lines=[];frame_size=0; // 重置本帧字段。
				} else {
					frame_size+=line.length+match[0].length;
					if(frame_size>4_000_000){throw new Error("事件数据超过读取上限");}
					if(line.startsWith(":")){continue;}
					// 忽略连接与心跳注释。
					const separator=line.indexOf(":"); // 仅首个冒号分隔字段。
					const field=separator<0? line:line.slice(0,separator); // 支持没有冒号的字段。
					let value=separator<0? "":line.slice(separator+1); // 保留数据中的其他冒号。
					if(value.startsWith(" ")) {
						value=value.slice(1);
					} // SSE 只去掉首个空格。
					if(field==="event") {
						event_name=value;
					} // 保存事件名称。
					if(field==="id"&&!value.includes("\0")) {
						event_id=value;
					} // 拒绝非法身份。
					if(field==="data") {
						data_lines.push(value);
					} // 保留多行数据。
				} // 结束字段处理。
			} // 结束完整行处理。
			if(buffer.length>4_000_000||frame_size+buffer.length>4_000_000) {
				throw new Error("事件数据超过读取上限");
			} // 防止损坏流无限增长。
			if(chunk.done) {
				break;
			} // 不提交没有空行结束的不完整事件。
		} // 结束网络流。
	} finally {
		await reader.cancel().catch(() => { });
		reader.releaseLock();
	} // 停止观察不会发送业务取消。
} // 结束 SSE 解码器。
