// 负责诊断输入的结构校验；不以字符检查代替故障语义判断。
export function diagnosis_input_error(description: string): string {
	if(!description.trim()) return "请填写故障现象、错误信息或日志";
	if(description.length>100000) return "故障描述不能超过100000字符";
	if(!/[\p{L}\p{Nd}]/u.test(description)) return "请补充故障现象、错误信息或日志，不能只输入标点或符号";
	return "";
}
