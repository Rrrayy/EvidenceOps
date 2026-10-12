export function backend_url(path: string): string {
	// 仅在服务端确定可信后端地址。
	const base=process.env.EVIDENCEOPS_API_URL??"http://127.0.0.1:8000"; // 本地默认接现有 FastAPI。
	return `${base.replace(/\/$/,"")}/api/v1/agent/${path}`; // 不允许浏览器指定任意代理目标。
} // 结束地址构造。
export async function backend_fetch(path: string,init: RequestInit={}): Promise<Response> {
	// 统一禁用缓存，历史状态不能陈旧。
	return fetch(backend_url(path),{ ...init,cache: "no-store" }); // 长流不使用短请求超时。
} // 结束后端访问。
export async function backend_error(response: Response): Promise<string> {
	// 保留用户能处理的后端错误。
	const data=await response.json().catch(() => null); // 非 JSON 网关错误也要处理。
	return (
		data?.message??
		(Array.isArray(data?.detail)? "输入无效，请检查故障描述":`服务请求失败（${response.status}）`)
	); // 不暴露代理异常堆栈。
} // 结束错误转换。
