// 只读校验真实归档和终止事件，不创建 Run、不调用模型、不修改数据库。
import assert from "node:assert/strict";
import { result_schema,event_schema,terminal_events } from "../src/lib/contracts";

async function audit_history(){
	const base=process.env.EVIDENCEOPS_AUDIT_URL??"http://127.0.0.1:3013/api/backend";
	let offset=0;
	let count=0;
	let terminal_count=0;
	const failures:{run_id:string;message:string}[]=[];
	while(true){
		const response=await fetch(`${base}/runs?limit=100&offset=${offset}`);
		assert.ok(response.ok,`历史列表读取失败：${response.status}`);
		const listing=await response.json();
		for(const item of listing.items){
			try{
				const detail_response=await fetch(`${base}/runs/${encodeURIComponent(item.run_id)}`);
				assert.ok(detail_response.ok);
				const detail=result_schema.parse(await detail_response.json());
				assert.equal(detail.run_id,item.run_id);
				assert.equal(detail.status,item.status);
				const event_response=await fetch(`${base}/runs/${encodeURIComponent(item.run_id)}/events`);
				assert.ok(event_response.ok);
				const archive=await event_response.json();
				for(const input of archive.events){
					const event=event_schema.parse(input);
					assert.equal(event.run_id,item.run_id);
					if(terminal_events.has(event.event)){
						const result=result_schema.parse(event.data.result);
						assert.equal(result.run_id,detail.run_id);
						assert.equal(result.status,detail.status);
						terminal_count++;
					}
				}
				count++;
			}catch(error){failures.push({run_id:item.run_id,message:String(error)});}
		}
		if(!listing.has_more){break;}
		offset+=listing.items.length;
		assert.ok(listing.items.length>0,"分页未推进");
	}
	console.log(JSON.stringify({passed:failures.length===0,count,terminal_count,failures},null,2));
	if(failures.length){process.exitCode=1;}
}
audit_history().catch(error=>{console.error(String(error));process.exitCode=1;});
