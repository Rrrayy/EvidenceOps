// 模型连接接口的状态、类型与安全展示工具。
export type ConnectionStatus="unverified"|"verifying"|"ready"|"partial"|"stale"|"failed"; // 验证状态与连接是否存在分开表达。
export type CapabilityStatus="verified"|"unsupported"|"unknown"; // 目录出现不意味着能力通过。
export interface ModelOption {
	// 只接受有来源的模型信息。
	id: string; // 供应商模型 ID。
	source: "catalog"|"recommended"|"custom"; // 展示目录来源。
	updated_at?: string|null; // 未提供更新时间时不推测。
	tool_calling?: CapabilityStatus; // 工具调用与结果关联能力。
	structured_report?: CapabilityStatus; // EvidenceOps 报告输出能力。
} // 结束模型目录类型。
export interface ModelConnection {
	// 读取响应绝不包含 API Key。
	id: string; // 稳定连接标识。
	name: string; // 用户自定义名称。
	provider_id: string; // 供应商和协议分别存储。
	protocol: "chat_completions"; // 当前代码实际适配的协议。
	endpoint_display: string; // 由后端输出安全展示地址。
	default_model: string; // 连接自身默认模型。
	config_version: number; // 编辑及验证并发控制版本。
	status: ConnectionStatus; // 后端最终判断能否执行。
	verified_at: string|null; // 最近验证时间。
	is_default: boolean; // 全局默认与工作台临时选择分开。
	editable: boolean; // 系统连接权限由后端声明。
} // 结束连接读取类型。
export const connection_labels: Record<ConnectionStatus,string>={
	unverified: "未验证",
	verifying: "验证中",
	ready: "验证通过",
	partial: "部分能力未通过",
	stale: "配置已修改，需要重新验证",
	failed: "验证失败"
}; // 状态必须用文字表达。
export function safe_endpoint(value: string): string {
	// 展示时仅保留协议、主机及端口，路径也可能携带密钥。
	try {
		// 无效地址不能直接回显敏感原文。
		const endpoint=new URL(value); // 解析凭据与查询参数。
		if(!["https:","http:"].includes(endpoint.protocol)) {
			return "地址格式无效";
		} // 限定展示协议。
		return endpoint.origin; // 去除用户信息、路径、查询及片段。
	} catch {
		return "地址格式无效";
	} // 不在错误中输出原值。
} // 安全展示不替代后端地址策略。
export function draft_error(name: string,endpoint: string,model: string): string {
	// 仅校验准备表单，不表示连接可用。
	if(!name.trim()) {
		return "请填写连接名称";
	} // 用户名称是连接身份的展示字段。
	if(safe_endpoint(endpoint)==="地址格式无效") {
		return "请填写有效的 HTTP 或 HTTPS 接口地址";
	} // 后端仍需限制允许范围。
	if(!model.trim()) {
		return "请填写模型 ID；目录尚未接通，仍可手动填写";
	} // 目录失败不阻断手填。
	return ""; // 这里只通过格式校验。
} // 结束草稿校验。
export function token_limits_error(values: { context_window: string; max_output: string; safety_margin: string; max_run: string }): string {
	const fields=[
		["context_window","上下文窗口",10_000_000,true],
		["max_output","单次输出上限",1_000_000,true],
		["safety_margin","安全余量",1_000_000,false],
		["max_run","单次诊断预算",10_000_000,true]
	] as const;
	for(const [key,label,maximum,positive] of fields) {
		const value=values[key];
		if(value==="") continue;
		const number=Number(value);
		if(!Number.isInteger(number)||number<(positive?1:0)) return `${label}必须是${positive?"正整数":"非负整数"}`;
		if(number>maximum) return `${label}不能超过 ${maximum.toLocaleString("zh-CN")} Token`;
	}
	const context=Number(values.context_window);
	const output=Number(values.max_output);
	const margin=Number(values.safety_margin);
	if(values.context_window!==""&&values.max_output!==""&&values.safety_margin!==""&&output+margin>=context) {
		return "输出上限与安全余量必须小于上下文窗口";
	}
	return "";
} // 保存前校验前端输入与后端容量约束一致。
