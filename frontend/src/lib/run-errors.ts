// 负责将网络、解析和契约异常转换为可处理的界面提示，不泄露内部校验数据。
import { ZodError } from "zod";

export function run_error_message(reason:unknown){
	if(reason instanceof ZodError){return "运行数据格式不兼容，暂时无法完整显示。请保留运行 ID 并联系维护人员，或稍后重试。";}
	if(reason instanceof SyntaxError){return "服务返回的数据无法读取，请稍后恢复观察。";}
	if(reason instanceof TypeError){return "无法连接诊断服务，请检查服务状态后重试。";}
	return reason instanceof Error?reason.message:"读取运行失败，请稍后重试。";
}
