import { z } from "zod"; // 评测导入也需要边界校验。
const check_schema=z.object({ name: z.string(),passed: z.boolean() }); // 自动规则只有通过与失败。
const review_schema=z
	.object({
		status: z.enum(["pending","passed","failed"]),
		criteria: z.array(z.string()),
		notes: z.string().optional()
	})
	.passthrough(); // 保留当前审核状态和标准。
export const evaluation_schema=z
	.object({
		schema_version: z.literal(1),
		batch_id: z.string(),
		mode: z.string(),
		summary: z.object({
			case_count: z.number().int().nonnegative(),
			rule_passed_count: z.number().int().nonnegative(),
			semantic_review_pending: z.number().int().nonnegative(),
			execution_error_count: z.number().int().nonnegative()
		}),
		results: z.array(
			z
				.object({
					case_id: z.string(),
					checks: z.array(check_schema),
					semantic_review: review_schema,
					wall_duration_ms: z.number().nonnegative().optional(),
					execution_error: z.string().nullable().optional()
				})
				.passthrough()
		)
	})
	.superRefine((data,context) => {
		// 只接受仓库当前版本。
		if(data.summary.case_count!==data.results.length) {
			context.addIssue({ code: "custom",message: "案例数量与评测结果不一致" });
		} // 拒绝缺失案例的报告。
		if(new Set(data.results.map((item) => item.case_id)).size!==data.results.length) {
			context.addIssue({ code: "custom",message: "案例 ID 重复" });
		} // 不允许重复案例抬高统计。
		const passed=data.results.filter(
			(item) => item.checks.length>0&&item.checks.every((check) => check.passed)
		).length; // 从实际规则计算通过数。
		if(passed!==data.summary.rule_passed_count) {
			context.addIssue({ code: "custom",message: "规则通过数与案例结果不一致" });
		} // 不盲信外部摘要。
		if(
			data.results.filter((item) => item.semantic_review.status==="pending").length!==
			data.summary.semantic_review_pending
		) {
			context.addIssue({ code: "custom",message: "待审核数量与案例不一致" });
		} // 审核统计必须有逐条依据。
		if(data.results.filter(item=>Boolean(item.execution_error)).length!==data.summary.execution_error_count){
			context.addIssue({code:"custom",message:"执行错误数量与案例不一致"});
		}
	}); // 结束评测一致性校验。
export type Evaluation=z.infer<typeof evaluation_schema>; // 页面保持同一数据结构。
