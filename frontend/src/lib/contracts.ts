import { z } from "zod"; // 在网络边界验证实际后端数据。
export const capability_schema=z.object({
	persistence:z.boolean(),provider_mode:z.string(),storage_management:z.boolean().optional(),
	source_mode:z.string().optional(),knowledge_search:z.boolean().optional(),
	parsed_logs:z.boolean().optional(),parsed_log_sources:z.array(z.string().min(1).max(100)).max(16).optional()
});
export const status_schema=z.enum(["pending","running","succeeded","failed","cancelled"]); // 与 Run 状态机一致。
const claim_schema=z.object({ text: z.string(),evidence_ids: z.array(z.string()) }); // 每个判断保留其真实引用。
export const evidence_schema=z.object({
	evidence_id: z.string(),
	source: z.string(),
	summary: z.string(),
	observed_at: z.string(),
	source_ref: z.string(),
	content_hash: z.string(),
	source_version: z.string().nullable(),
	content_snapshot: z.string().nullable().optional(),
	source_metadata: z.object({
		document_id: z.string().nullable().optional(),
		source_ref: z.string().nullable().optional(),
		chunk_id: z.string().nullable().optional(),
		chunk_set_id: z.string().nullable().optional(),
		embedding_set_id: z.string().nullable().optional(),
		config_fingerprint: z.string().nullable().optional(),
		heading_path: z.array(z.string()).nullable().optional(),
		start_offset: z.number().int().nullable().optional(),
		end_offset: z.number().int().nullable().optional(),
		score: z.number().nullable().optional(),
		rank: z.number().int().nullable().optional(),
		retrieval_method: z.string().nullable().optional(),
		retrieval_details: z.record(z.string(),z.unknown()).nullable().optional(),
		source_id:z.string().optional(),source_role:z.string().optional(),observed_at_basis:z.string().optional(),
		input_sha256:z.string().optional(),hash_basis:z.string().optional(),parser_status:z.string().optional(),
		selection:z.record(z.string(),z.unknown()).optional(),line_ranges:z.array(z.array(z.number())).optional()
	}).nullable().optional()
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
	,handler_started_at: z.string().nullable().optional(),handler_finished_at: z.string().nullable().optional()
	,estimated_input_tokens: z.number().int().nonnegative().nullable().optional()
	,reserved_output_tokens: z.number().int().nonnegative().nullable().optional()
	,reported_input_tokens: z.number().int().nonnegative().nullable().optional()
	,reported_output_tokens: z.number().int().nonnegative().nullable().optional()
	,reported_total_tokens: z.number().int().nonnegative().nullable().optional()
	,usage_status: z.enum(["complete","partial","missing","invalid","unknown"]).nullable().optional()
	,payload_hash: z.string().nullable().optional()
}); // 定义收尾归档中的完整执行记录。
export const result_schema=z.object({
	model_config: z
		.object({
			connection_id: z.string().nullable().optional(),
			connection_name: z.string().nullable().optional(),
			provider_id: z.string().nullable().optional(),
			provider: z.string().nullable().optional(),
			model_id: z.string().nullable().optional(),
			requested_model_id: z.string().nullable().optional(),
			config_version: z.number().nullable().optional(),
			context_window_tokens: z.number().int().positive().nullable().optional(),
			max_output_tokens: z.number().int().positive().nullable().optional(),
			safety_margin_tokens: z.number().int().nonnegative().nullable().optional(),
			max_run_tokens: z.number().int().positive().nullable().optional(),
			limits_source: z.string().nullable().optional(),
			limits_verified_at: z.string().nullable().optional(),
			estimator_id: z.string().nullable().optional()
		})
		.nullable()
		.optional(), // 实际 Run 快照，不取当前默认值。
	run_id: z.string(),
	request_id: z.string(),
	description: z.string().optional(),
	status: status_schema,
	error_code: z.string().nullable(),
	error_detail: z.object({ code: z.string(),message: z.string(),missing_information: z.array(z.string()).nullable().optional() }).nullable().optional(),
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
export const history_schema=z.object({
	items:z.array(result_schema.pick({run_id:true,description:true,status:true,created_at:true,started_at:true,finished_at:true,error_code:true,error_detail:true})),
	has_more:z.boolean()
});
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
export const source_labels: Record<string,string>={ log: "日志",metric: "指标",config: "配置",knowledge: "知识参考" }; // 翻译当前证据类型。
export const tool_labels: Record<string,string>={
	query_service_logs: "查询服务日志",
	query_service_metrics: "查询运行指标",
	query_service_config: "查询历史配置",
	search_knowledge: "检索知识资料",
	query_parsed_logs: "解析受控日志"
}; // 已知工具使用业务名称，未知工具保留原名。
export const example_description=
	"请使用query_service_logs和query_service_metrics查询order-service在production环境2026-10-05T10:00:00+08:00至2026-10-05T10:10:00+08:00的rpc_timeout日志与线程池指标，各limit=50，并使用query_service_config查询2026-10-05T10:02:00+08:00生效配置。结合证据分析，区分已确认事实与原因假设，不要把配置允许重试当作已经发生重试。"; // 使用仓库中真实可复现的示例。
