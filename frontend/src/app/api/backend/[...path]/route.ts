// 负责白名单同源代理、维护令牌转发及备份原文传输。
import { backend_fetch } from "@/lib/backend";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
export const runtime="nodejs";
async function forward(request: Request,context: { params: Promise<{ path: string[] }> }) {

	const { path }=await context.params;
	const route=path.join("/");
	const storage=(request.method==="GET"&&(["storage/status","setup/status"].includes(route)||(path[0]==="storage"&&path.length===3&&["operations","backups"].includes(path[1]))))||(request.method==="POST"&&["storage/check","storage/operations","storage/backups/import"].includes(route));
	const management=
		(request.method==="GET"&&
			(["model-services","model-connections"].includes(route)||
				(path[0]==="model-connections"&&path.length===2&&path[1]!=="default")))||
		(request.method==="POST"&&route==="model-connections")||
		(["PATCH","DELETE"].includes(request.method)&&
			path[0]==="model-connections"&&
			path.length===2&&
			path[1]!=="default")||
		(request.method==="PUT"&&route==="model-connections/default")||
		(request.method==="POST"&&
			path[0]==="model-connections"&&
			path.length===3&&
			["catalog","validation"].includes(path[2]));
	const valid=
		management||storage||
		(request.method==="GET"&&
			(path.join("/")==="capabilities"||
				path.join("/")==="runs"||
				(path[0]==="runs"&&path.length===2)||
				(path[0]==="runs"&&
					path[2]==="events"&&
					(path.length===3||(path.length===4&&path[3]==="stream")))))||
		(request.method==="POST"&&path[0]==="runs"&&path.length===3&&path[2]==="cancel");
	if(!valid) {
		return Response.json({ message: "接口不存在" },{ status: 404 });
	}
	try {

		const origin=request.headers.get("origin"); // 跨站来源不能通过本机代理写凭据。
		if(
			request.method!=="GET"&&
			origin&&
			new URL(origin).host!==(request.headers.get("host")??new URL(request.url).host)
		) {
			return Response.json({ message: "不允许跨站写入请求" },{ status: 403 });
		}
		const query=new URL(request.url).search;
		const headers:Record<string,string>={};
		if((management||storage)&&request.method!=="GET") { headers["Content-Type"]="application/json"; }
		if(storage) {
			const user_directory=process.env.USERPROFILE??process.env.HOME;
			const directory=process.env.EVIDENCEOPS_DATA_DIR??(process.platform==="win32"?join(process.env.LOCALAPPDATA??join(user_directory??"","AppData","Local"),"EvidenceOps"):join(process.env.XDG_DATA_HOME??join(user_directory??"",".local","share"),"evidenceops"));
			const token=await readFile(process.env.EVIDENCEOPS_ADMIN_TOKEN_FILE??join(directory,"admin.token"),"utf8").catch(()=>"");
			if(token) { headers["X-EvidenceOps-Admin"]=token.trim(); }
		}
		const response=await backend_fetch(path.map(encodeURIComponent).join("/")+query,{
			method: request.method,
			headers,
			body: (management||storage)&&request.method!=="GET"?route==="storage/backups/import"?await request.text():JSON.stringify(await request.json()):undefined, // 备份不得在 JavaScript 中重新序列化数字。
			signal: request.signal
		});
		return new Response(response.body,{
			status: response.status,
			headers: {
				"Content-Type": response.headers.get("content-type")??"application/json",
				"Cache-Control": "no-store",
				"X-Accel-Buffering": "no",
				"Content-Disposition": response.headers.get("content-disposition")??"inline"
			}
		});
	} catch {
		return Response.json({ message: "无法连接诊断服务，请确认 FastAPI 已启动" },{ status: 502 });
	}
}
export const GET=forward;
export const POST=forward;

export const PATCH=forward;
export const PUT=forward;
export const DELETE=forward;
