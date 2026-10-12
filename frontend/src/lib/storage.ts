// 负责安装存储接口的类型校验、状态读取和维护请求。
import { z } from "zod";
const operation_schema=z.object({
	id:z.string(),action:z.string(),status:z.enum(["waiting","running","succeeded","failed"]),stage:z.string(),message:z.string(),created_at:z.string(),finished_at:z.string().optional(),backup_id:z.string().optional()
});
export const storage_schema=z.object({
	supported:z.literal(true),state:z.string(),message:z.string(),mode:z.enum(["sqlite","postgres"]),version:z.number().int(),setup_completed:z.boolean(),source_mode:z.literal("samples"),schema_version:z.string().nullable(),data_location:z.string(),database_display:z.string(),active_runs:z.number().int(),
	postgres:z.object({host:z.string(),port:z.number(),database:z.string(),user:z.string(),password_configured:z.boolean()}),
	backups:z.array(z.object({id:z.string(),created_at:z.string(),label:z.string(),size_bytes:z.number(),sha256:z.string(),credentials_included:z.boolean()})),operations:z.array(operation_schema)
});
export type StorageStatus=z.infer<typeof storage_schema>;
export type StorageOperation=z.infer<typeof operation_schema>;
export async function storage_request(path:string,body?:unknown,signal?:AbortSignal,raw=false){ // 备份按原文本转发，避免 JavaScript 改写数字影响校验和。
	const response=await fetch(`/api/backend/${path}`,{method:body===undefined?"GET":"POST",cache:"no-store",signal,headers:body===undefined?undefined:{"Content-Type":"application/json"},body:body===undefined?undefined:raw?String(body):JSON.stringify(body)});
	const data=await response.json().catch(()=>null);
	if(!response.ok){throw new Error(response.status===404?"当前启动的是开发 API，安装管理尚未启用。请使用安装版入口启动服务。":data?.message??`存储请求失败（${response.status}）`);}
	return data;
}
