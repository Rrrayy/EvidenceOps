// 负责将网络、解析和契约异常转换为可处理的界面提示，不泄露内部校验数据。
import { ZodError } from "zod";

const backend_error_labels: Record<string,string>={
	CONTEXT_BUDGET_EXCEEDED:"当前模型请求超出上下文容量，未提交给模型服务。",
	RUN_TOKEN_BUDGET_EXCEEDED:"本次诊断累计 Token 预算不足，当前请求未继续提交给模型服务。",
	TOKEN_USAGE_INVALID:"模型返回的 Token 计量格式无效，无法统计本次用量。"
};

export function run_error_code_message(code: string|null|undefined){
	return code?backend_error_labels[code]??null:null;
}

export function run_error_message(reason:unknown){
	if(reason instanceof ZodError){return "运行数据格式不兼容，暂时无法完整显示。请保留运行 ID 并联系维护人员，或稍后重试。";}
	if(reason instanceof SyntaxError){return "服务返回的数据无法读取，请稍后恢复观察。";}
	if(reason instanceof TypeError){return "无法连接诊断服务，请检查服务状态后重试。";}
	return reason instanceof Error?reason.message:"读取运行失败，请稍后重试。";
}
