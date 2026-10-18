// 负责按实际调用身份展示诊断时间线、耗时与失败详情。
"use client";
import { BrainCircuit,Check,Clock3,Database,LoaderCircle,X,ChevronDown } from "lucide-react";
import { tool_labels,type RunEvent,type RunResult } from "@/lib/contracts";
import { run_error_code_message } from "@/lib/run-errors";

function token_value(value:number|undefined|null){
	return value==null?"未记录":value.toLocaleString("zh-CN");
}

const usage_labels:Record<string,string>={complete:"完整",partial:"部分",missing:"缺失",invalid:"无效",unknown:"未知"};

function TokenUsage({record}:{record:NonNullable<RunResult>["execution_records"][number]}){
	const has_usage=[record.estimated_input_tokens,record.reserved_output_tokens,record.reported_input_tokens,record.reported_output_tokens,record.reported_total_tokens].some((value)=>value!=null)||record.usage_status!=null;
	if(!has_usage){return null;}
	return <div className="token-usage" aria-label="Token 使用信息">
		<strong>Token 记录</strong>
		<dl>
			<div><dt>估算输入</dt><dd>{token_value(record.estimated_input_tokens)}</dd></div>
			<div><dt>单次输出上限</dt><dd>{token_value(record.reserved_output_tokens)}</dd></div>
			<div><dt>供应商输入</dt><dd>{token_value(record.reported_input_tokens)}</dd></div>
			<div><dt>供应商输出</dt><dd>{token_value(record.reported_output_tokens)}</dd></div>
			<div><dt>供应商总量</dt><dd>{token_value(record.reported_total_tokens)}</dd></div>
		</dl>
		<p className="field-note">状态：{record.usage_status?usage_labels[record.usage_status]??"未知":"未记录"}。估算值是启发式结果，不是供应商账单。</p>
	</div>;
}
export function Trace({ events,result }: { events: RunEvent[]; result: RunResult|null }) {

	const starts=events.filter((item) => item.event==="model_started"||item.event==="tool_started");
	return (
		<div className="trace-list">
			{starts.map((item,index) => {

				const model=item.event==="model_started";
				const identity=model? item.data.model_request_id:item.data.tool_call_id;
				const finish=events.find(
					(event) =>
						event.event===(model? "model_finished":"tool_finished")&&
						(model? event.data.model_request_id:event.data.tool_call_id)===identity
				);
				const record=result?.execution_records.find(
					(entry) => (model? entry.model_request_id:entry.tool_call_id)===identity
				);
				const status=
					finish?.data.status??
					(result&&["failed","cancelled","succeeded"].includes(result.status)? "unknown":"running");
				const Icon=
					status==="succeeded"
						? Check
						:status==="failed"||status==="cancelled"
							? X
							:status==="running"
								? LoaderCircle
								:Clock3;
				const name=model
					? `模型分析 · 第 ${item.data.model_round} 轮`
					:(tool_labels[String(item.data.tool_name)]??String(item.data.tool_name));
				return (
					<details className={`trace-item ${status}`} key={item.sequence}>
						<summary>
							<span className="trace-sequence" aria-label={`第 ${index+1} 次调用`}>{String(index+1).padStart(2,"0")}</span>
							<span className="trace-icon">
								{model? <BrainCircuit size={17} />:<Database size={17} />}
							</span>
							<span className="trace-title">
								{name}
								<small>
									{status==="running"
										? "正在执行"
										:status==="succeeded"
											? "执行完成"
											:status==="unknown"
												? "未记录完成事件"
												:status==="cancelled"
													? "已取消"
													:"执行失败"}
								</small>
							</span>
							<span className="trace-timing">
								{typeof finish?.data.duration_ms==="number"
									? `${(finish.data.duration_ms/1000).toFixed(2)}s`
									:""}
								<Icon size={14} className={status==="running"? "spin":""} />
							</span>
							<ChevronDown size={12} />
						</summary>
						<div className="trace-detail">
							<p>开始于 {new Date(item.occurred_at).toLocaleTimeString("zh-CN")}</p>
							{finish?.data.error_code? <p className="trace-failure"><span>失败位置：{name}</span><code>{String(finish.data.error_code)}</code></p>:null}
							{Boolean(finish?.data.error_code)&&<p className="trace-note">{run_error_code_message(String(finish?.data.error_code))??"服务返回了失败原因，请查看归档详情。"}</p>}
							{record?.query_arguments? (
								<pre>{JSON.stringify(record.query_arguments,null,2)}</pre>
							):(
								<p className="muted">
									{model
										? String(item.data.model??"模型名称未记录")
										:"查询参数在完整执行记录归档后提供。"}
								</p>
							)}
							{record&&<TokenUsage record={record}/>}
						</div>
					</details>
				);
			})}
			{events.some((item) => item.event==="run_cancel_requested")&&(
				<p className="trace-note">已接纳取消请求，等待终态确认。</p>
			)}
			{events.some((item) => ["run_completed","run_failed","run_cancelled"].includes(item.event))&&(
				<div className="trace-terminal">
						<Clock3 size={15} />
						运行已结束
				</div>
			)}
		</div>
	);
}
