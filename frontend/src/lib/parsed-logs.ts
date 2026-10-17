// 负责识别和校验归档日志快照；解析失败保留原文，不重读来源文件。
import { z } from "zod";
import type { Evidence } from "./contracts";
const counter=z.number().int().nonnegative().safe();
const event_schema=z.object({
	event_index:counter,line_start:counter.positive(),line_end:counter.positive(),
	raw_text:z.string(),raw_time:z.string(),timestamp:z.iso.datetime({offset:true}).nullable(),
	format:z.string(),level:z.string().nullable(),message:z.string(),warnings:z.array(z.string()),
	code_file:z.string().nullable().optional(),code_line:z.number().nullable().optional(),
	thread_id:z.string().nullable().optional(),event_kind:z.string().nullable().optional(),
	attributes:z.record(z.string(),z.unknown()).optional()
}).refine(event=>event.line_end>=event.line_start);
export const parsed_log_schema=z.object({
	schema_version:z.literal("log-evidence-v1"),source_id:z.string(),source_role:z.enum(["server","client","unknown"]),
	parser_status:z.enum(["complete","partial"]),events:z.array(event_schema).max(20),
	statistics:z.object({event_count:counter,unrecognized_count:counter,warning_count:counter,stop_reason:z.string().nullable(),stopped_early:z.boolean()}),
	selection:z.object({rule:z.string(),keyword:z.string().nullable(),limit:counter.min(1).max(20),selected_count:counter,omitted_count:counter,
		after_line:counter.optional(),last_examined_line:counter.optional(),next_after_line:counter.nullable().optional(),
		stop_reason:z.string().optional(),oversized_count:counter.optional(),remaining_budget_count:counter.optional(),snapshot_scope:z.string().optional()}),
	input_sha256:z.string(),hash_basis:z.string(),imported_at:z.string()
}).refine(snapshot=>snapshot.selection.selected_count===snapshot.events.length&&snapshot.selection.omitted_count+snapshot.events.length===snapshot.statistics.event_count&&snapshot.statistics.stopped_early===(snapshot.parser_status==="partial"));
export function is_parsed_log(evidence:Evidence){
	return evidence.source==="log"&&(evidence.source_version==="log-evidence-v1"||evidence.source_ref.startsWith("parsed-log:"));
}
export function read_parsed_log(evidence:Evidence){
	if(!is_parsed_log(evidence)||evidence.content_snapshot==null){return null;}
	try{
		const parsed=parsed_log_schema.safeParse(JSON.parse(evidence.content_snapshot));
		return parsed.success?parsed.data:null;
	}catch{return null;}
}
export function event_time(event:{timestamp:string|null;raw_time:string}){
	// 保留后端时区表达；导入时间绝不用于补齐事件时间。
	return event.timestamp??`事件时间未知${event.raw_time?` · 原始时间 ${event.raw_time}`:""}`;
}
export function log_attribute(value:unknown):string{
	if(typeof value==="number"&&!Number.isSafeInteger(value)){return "数值超出安全整数范围，请核对归档原文";}
	return typeof value==="string"||typeof value==="boolean"||typeof value==="number"?String(value):"无法识别，请核对归档原文";
}
