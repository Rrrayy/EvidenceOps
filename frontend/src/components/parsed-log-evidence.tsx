// 负责以输入行号、原文和解析边界呈现本次运行的日志证据组。
import { useState } from "react";
import type { Evidence } from "@/lib/contracts";
import { event_time,read_parsed_log,log_attribute } from "@/lib/parsed-logs";
const roles={server:"服务端",client:"客户端",unknown:"角色未声明"};
const levels:Record<string,string>={trace:"Trace",debug:"Debug",info:"Info",warning:"Warning",error:"Error",fatal:"Fatal",unknown:"级别未知"};
const stop_reasons:Record<string,string>={event_limit:"达到事件数量上限",output_limit:"达到输出大小上限",input_limit:"达到输入大小上限",line_limit:"达到单行大小上限"};
export function ParsedLogEvidence({evidence}:{evidence:Evidence}){
	const [keyword,set_keyword]=useState("");
	const snapshot=read_parsed_log(evidence);
	if(!snapshot){return <section className="log-evidence"><p className="log-notice" role="status">{evidence.content_snapshot==null?"本次运行未记录日志正文。":"日志快照格式无法识别，以下保留归档原文。"}</p>{evidence.content_snapshot!=null&&<pre className="log-raw-fallback">{evidence.content_snapshot}</pre>}</section>;}
	const events=snapshot.events.filter(event=>event.raw_text.toLocaleLowerCase().includes(keyword.toLocaleLowerCase()));
	return <section className="log-evidence" aria-label="归档日志证据组">
		<div className="log-source-heading"><div><h3>{snapshot.source_id}</h3><span>{roles[snapshot.source_role]}</span></div><span className={`log-scan ${snapshot.parser_status}`}>{snapshot.parser_status==="partial"?"扫描不完整":"扫描完成"}</span></div>
		<div className="log-counts"><span>已解析 <strong>{snapshot.statistics.event_count}</strong></span><span>本组 <strong>{snapshot.events.length}</strong></span><span>未识别格式 <strong>{snapshot.statistics.unrecognized_count}</strong></span></div>
		{snapshot.parser_status==="partial"&&<p className="log-notice" role="status">扫描不完整：{stop_reasons[snapshot.statistics.stop_reason??""]??snapshot.statistics.stop_reason??"未记录停止原因"}。</p>}
		{snapshot.selection.omitted_count>0&&<p className="log-notice">{snapshot.selection.omitted_count} 条已解析事件未进入本证据组。</p>}
		<details className="log-event-details log-scope"><summary>解析范围与限制</summary>
			<p className="log-boundary">按输入顺序展示。解析警告和未识别格式表示解析覆盖情况，不等同于业务故障。</p>
			<p className="log-boundary">扫描不完整时，不能排除未扫描部分的故障。未选入事件可能受行范围、关键词、数量或正文预算限制，不代表它们均与故障相关。</p>
			<div className="log-selection"><span>本次选择</span><code>{snapshot.selection.keyword?`正文包含 ${snapshot.selection.keyword}`:"未指定关键词"}</code><span>最多 {snapshot.selection.limit} 条</span></div>
			{snapshot.selection.after_line!=null&&<p className="log-boundary">从输入行 {snapshot.selection.after_line} 之后读取，已检查至行 {snapshot.selection.last_examined_line??"未记录"}。{snapshot.selection.next_after_line!=null?`可通过 after_line=${snapshot.selection.next_after_line} 继续查询。`:"已到已解析事件末尾；不代表未扫描内容已被覆盖。"}</p>}
			{snapshot.selection.oversized_count!=null&&<p className="log-boundary">单条事件超出预算：{snapshot.selection.oversized_count} 条；本组剩余预算不足：{snapshot.selection.remaining_budget_count??0} 条。均跳过完整事件，没有截断原文。</p>}
			<p className="log-boundary">每次查询独立读取来源；跨次调用请核对输入哈希，来源文件变化时不能视为同一快照。</p>
		</details>
		<label className="log-filter">查找本组原文<input type="search" value={keyword} onChange={event=>set_keyword(event.target.value)} placeholder="仅查找已归档事件，不请求来源" /></label>
		<p className="log-match-count" aria-live="polite">显示 {events.length} / {snapshot.events.length} 条</p>
		{!snapshot.events.length?<p className="log-empty">本次选择没有返回事件，不能据此判断服务没有问题。</p>:!events.length?<p className="log-empty">本组没有匹配原文。请修改查找内容。</p>:<ol className="log-events">{events.map(event=><li key={event.event_index} className="log-event">
			<header><span className="log-line-label">输入行 {event.line_start}{event.line_end!==event.line_start?`–${event.line_end}`:""}</span><span className={`log-level ${["error","fatal","warning"].includes(event.level??"")?event.level:"neutral"}`}>{event.level?levels[event.level]??event.level:"级别未记录"}</span><span>{event.format==="unknown"?"格式未识别":event.format}</span></header>
			<p className="log-event-time">{event_time(event)}</p>
			<pre className="log-original">{event.raw_text}</pre>
			{event.warnings.length>0&&<details className="log-event-details"><summary>解析提示（{event.warnings.length}）</summary><ul>{event.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></details>}
			<details className="log-event-details"><summary>解析字段</summary><dl><dt>消息</dt><dd>{event.message||"未记录"}</dd><dt>源码位置（非日志行号）</dt><dd>{event.code_file??"未记录"}{event.code_line!=null?Number.isSafeInteger(event.code_line)?`:${event.code_line}`:" · 行号超出安全整数范围，请核对归档原文":""}</dd><dt>线程</dt><dd>{event.thread_id??"未记录"}</dd><dt>事件类型</dt><dd>{event.event_kind??"未记录"}</dd>{Object.entries(event.attributes??{}).map(([name,value])=><div className="log-attribute" key={name}><dt>{name}</dt><dd>{log_attribute(value)}</dd></div>)}</dl><p className="muted">其他字段以归档原始 JSON 为准。</p></details>
		</li>)}</ol>}
		<details className="log-provenance"><summary>快照追溯与归档原文</summary><dl className="evidence-metadata"><dt>导入时间（非事件时间）</dt><dd>{snapshot.imported_at}</dd><dt>输入快照 SHA-256</dt><dd><code>{snapshot.input_sha256}</code></dd><dt>哈希范围</dt><dd>{snapshot.hash_basis==="full_adapter_input_snapshot_bytes"?"Adapter 本次受限输入快照的全部字节；不证明来源文件此后未变化。":snapshot.hash_basis}</dd><dt>选择规则</dt><dd>{snapshot.selection.rule}</dd></dl><pre className="log-raw-fallback">{evidence.content_snapshot}</pre></details>
	</section>;
}
