// 隔离注入损坏档案、错误身份和网络故障，验证界面不伪造运行状态。
async(page)=>{
	const check=(condition,message)=>{if(!condition){throw new Error(message);}};
	const errors=[];
	page.on("pageerror",error=>errors.push(error.message));
	const time="2026-10-15T01:00:00Z";
	const result={run_id:"resilience-run",request_id:"req",description:"隔离异常验收",status:"failed",error_code:"EVIDENCE_INSUFFICIENT",error_detail:{code:"EVIDENCE_INSUFFICIENT",message:"缺少现场观测",missing_information:["错误栈"]},model_config:{provider:"qianwen-platform",model_id:"qwen3.8-flash"},created_at:time,started_at:time,finished_at:time,evidences:[],report:null,execution_records:[]};
	let mode="invalid-model";
	let posts=0;
	let detail_reads=0;
	await page.route("**/api/diagnosis",route=>{posts++;return route.fulfill({status:500,json:{message:"测试禁止创建"}});});
	await page.route("**/api/backend/**",async route=>{
		const path=new URL(route.request().url()).pathname;
		if(path.endsWith("/capabilities")){return route.fulfill({json:{persistence:true,provider_mode:"mock"}});}
		if(path.endsWith("/setup/status")){return route.fulfill({json:{supported:false}});}
		if(path.endsWith("/runs")){return route.fulfill({json:mode==="invalid-list"?{items:null,has_more:true}:{items:[],has_more:false}});}
		if(path.endsWith("/events/stream")){
			const conflict={event:"run_completed",sequence:1,run_id:result.run_id,occurred_at:time,data:{result}};
			return route.fulfill({contentType:"text/event-stream",body:mode==="terminal-conflict"?`data: ${JSON.stringify(conflict)}\n\n`:""});
		}
		if(path.endsWith(`/runs/${result.run_id}`)){
			detail_reads++;
			if(mode==="network"){return route.abort("failed");}
			if(mode==="bad-json"){return route.fulfill({contentType:"application/json",body:"not JSON"});}
			const data=mode==="invalid-model"?{...result,model_config:{model_id:{private_value:"do-not-expose"}}}:mode==="wrong-identity"||mode==="wrong-final"&&detail_reads>1?{...result,run_id:"another-run"}:result;
			return route.fulfill({json:data});
		}
		return route.fulfill({status:503,json:{message:"隔离未提供的能力"}});
	});
	const checks=[];
	for(const scenario of ["invalid-model","wrong-identity","bad-json","network","terminal-conflict","wrong-final"]){
		mode=scenario;
		detail_reads=0;
		await page.goto(`http://127.0.0.1:3011/?run=${result.run_id}`);
		const expected=scenario==="invalid-model"?"格式不兼容":scenario==="bad-json"?"无法读取":scenario==="network"?"无法连接":scenario==="terminal-conflict"?"状态不一致":"不属于当前诊断";
		await page.getByRole("alert").filter({hasText:expected}).waitFor();
		check(await page.getByRole("button",{name:"取消诊断",exact:true}).count()===0,`${scenario} 不得出现未经确认的取消按钮`);
		check(await page.locator(".status-badge.running").count()===0,`${scenario} 不得显示诊断中`);
		check(await page.locator(".report").count()===0,`${scenario} 不得显示成功报告`);
		const text=await page.locator("main").innerText();
		check(!text.includes("invalid_type")&&!text.includes("do-not-expose"),"不能暴露校验内部信息");
		checks.push(scenario);
	}
	mode="invalid-list";
	await page.goto("http://127.0.0.1:3011/?view=history");
	await page.getByRole("alert").filter({hasText:"格式不兼容"}).waitFor();
	check(await page.locator(".empty-panel,.pagination").count()===0,"损坏列表不能显示为空或有分页");
	mode="valid-list";
	await page.getByRole("button",{name:"重试",exact:true}).click();
	await page.getByRole("heading",{name:"这里还没有运行记录",exact:true}).waitFor();
	checks.push("malformed-list-retry");
	await page.getByRole("textbox",{name:"搜索诊断"}).fill("无匹配记录");
	await page.getByRole("button",{name:"搜索",exact:true}).click();
	await page.getByRole("heading",{name:"没有匹配的运行记录",exact:true}).waitFor();
	checks.push("filtered-empty-copy");
	check(posts===0,"回查和恢复不能创建诊断");
	check(errors.length===0,`页面异常：${errors.join(";")}`);
	return {passed:true,mode:"isolated-fault-injection",checks,posts};
}
