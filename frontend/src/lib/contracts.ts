import { z } from "zod"; // 在网络边界验证实际后端数据。
export const status_schema=z.enum(["pending","running","succeeded","failed","cancelled"]); // 与 Run 状态机一致。
const claim_schema=z.object({ text: z.string(),evidence_ids: z.array(z.string()) }); // 每个判断保留其真实引用。
export const evidence_schema=z.object({
	evidence_id: z.string(),
	source: z.string(),
	summary: z.string(),
	observed_at: z.string(),
	source_ref: z.string(),
	content_hash: z.string(),
	source_version: z.string().nullable()
}); // 只展示 API 实际提供的证据字段。
export const record_schema=z.object({
	kind: z.string(),
	model_round: z.number().nullable(),
	model_request_id: z.string().nullable(),
	tool_name: z.string().nullable(),
	tool_call_id: z.string().nullable(),
	query_arguments: z.record(z.string(),z.unknown()).nullable(),
	started_at: z.string(),
	finished_at: z.string(),
	duration_ms: z.number(),
	status: z.string(),
	error_code: z.string().nullable()
}); // 定义收尾归档中的完整执行记录。
export const result_schema=z.object({
	model_config: z
		.object({
			connection_id: z.string(),
			connection_name: z.string(),
			provider_id: z.string(),
			model_id: z.string(),
			requested_model_id: z.string().optional(),
			config_version: z.number()
		})
		.nullable()
		.optional(), // 实际 Run 快照，不取当前默认值。
	run_id: z.string(),
	request_id: z.string(),
	description: z.string().optional(),
	status: status_schema,
	error_code: z.string().nullable(),
	error_detail: z.object({ code: z.string(),message: z.string() }).nullable().optional(),
	created_at: z.string(),
	started_at: z.string().nullable(),
	finished_at: z.string().nullable(),
	evidences: z.array(evidence_schema),
	report: z
		.object({
			root_cause: claim_schema,
			recommendations: z.array(claim_schema),
			confidence: z.number().min(0).max(1),
			limitations: z.string()
		})
		.nullable(),
	execution_records: z.array(record_schema)
}); // 统一同步、历史与终止事件的结果。
export const event_schema=z.object({
	event: z.string(),
	sequence: z.number().int().nonnegative(),
	run_id: z.string().nullable(),
	occurred_at: z.string(),
	data: z.record(z.string(),z.unknown())
}); // 验证业务事件信封。
export type RunResult=z.infer<typeof result_schema>; // 从校验规则推导结果类型。
export type RunEvent=z.infer<typeof event_schema>; // 从校验规则推导事件类型。
export type Evidence=z.infer<typeof evidence_schema>; // 从校验规则推导证据类型。
export type RunStatus=z.infer<typeof status_schema>; // 保持界面状态与后端一致。
export const terminal_events=new Set(["run_completed","run_failed","run_cancelled"]); // 传输失败不属于业务终态。
export const status_labels: Record<string,string>={
	pending: "等待执行",
	running: "诊断中",
	succeeded: "已完成",
	failed: "诊断失败",
	cancelled: "已取消"
}; // 提供统一中文状态。
export const source_labels: Record<string,string>={ log: "日志",metric: "指标",config: "配置" }; // 翻译当前证据类型。
export const tool_labels: Record<string,string>={
	query_service_logs: "查询服务日志",
	query_service_metrics: "查询运行指标",
	query_service_config: "查询历史配置"
}; // 已知工具使用业务名称，未知工具保留原名。
export const example_description=
	"请使用query_service_logs和query_service_metrics查询order-service在production环境2026-10-05T10:00:00+08:00至2026-10-05T10:10:00+08:00的rpc_timeout日志与线程池指标，各limit=50，并使用query_service_config查询2026-10-05T10:02:00+08:00生效配置。结合证据分析，区分已确认事实与原因假设，不要把配置允许重试当作已经发生重试。"; // 使用仓库中真实可复现的示例。
