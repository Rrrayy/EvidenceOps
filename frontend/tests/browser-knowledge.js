// 使用隔离的接口测试数据验收知识证据、拒答和历史回放，不调用真实模型。
async(page)=>{
	const check=(condition,message)=>{if(!condition){throw new Error(message);}};
	const errors=[];
	page.on("pageerror",error=>errors.push(error.message));
	const timestamp="2026-10-15T01:00:00Z";
	const evidence={evidence_id:"knowledge-1",source:"knowledge",summary:"连接池排查参考",observed_at:timestamp,source_ref:"knowledge:chunk-1",source_version:"version-at-run",content_hash:"hash",content_snapshot:'<script>window.knowledge_injected=true</script>\n中文😀'+"长模型来源".repeat(100),source_metadata:{heading_path:["运行手册","连接池"],source_ref:"manual.md",document_id:"manual",score:0,rank:1,start_offset:0,end_offset:500}};
	const result={run_id:"handoff-knowledge",request_id:"req",description:"接口测试：连接池故障",status:"failed",error_code:"EVIDENCE_INSUFFICIENT",error_detail:{code:"EVIDENCE_INSUFFICIENT",message:"缺少现场连接池观测",missing_information:["完整错误栈","复现步骤及版本"]},created_at:timestamp,started_at:timestamp,finished_at:timestamp,evidences:[evidence,{...evidence,evidence_id:"knowledge-2",content_snapshot:"第二个片段"}],report:null,execution_records:[]};
	const events=[
		{event:"run_started",data:{status:"running"}},
		{event:"tool_started",data:{tool_name:"search_knowledge",tool_call_id:"search-1"}},
		{event:"tool_finished",data:{tool_name:"search_knowledge",tool_call_id:"search-1",status:"succeeded",duration_ms:20}},
		{event:"run_failed",data:{result}}
	].map((event,index)=>({...event,sequence:index+1,run_id:result.run_id,occurred_at:timestamp}));
	await page.route("**/api/backend/**",async route=>{
		const path=new URL(route.request().url()).pathname;
		if(path.endsWith("/capabilities")){await route.fulfill({json:{persistence:true,provider_mode:"mock",knowledge_search:true}});}
		else if(path.endsWith("/setup/status")){await route.fulfill({json:{supported:false}});}
		else if(path.endsWith("/events/stream")){await route.fulfill({contentType:"text/event-stream",body:events.map(event=>`event: ${event.event}\ndata: ${JSON.stringify(event)}\n\n`).join("")});}
		else if(path.endsWith(`/runs/${result.run_id}`)){await route.fulfill({json:result});}
		else if(path.endsWith("/runs")){await route.fulfill({json:{items:[result],has_more:false}});}
		else{await route.fulfill({status:503,json:{message:"测试模式未提供该能力"}});}
	});
	await page.setViewportSize({width:1440,height:1000});
	await page.goto(`http://127.0.0.1:3011/?run=${result.run_id}`);
	await page.getByRole("heading",{name:"证据不足，需补充信息",exact:true}).waitFor();
	check(await page.getByText("完整错误栈",{exact:true}).count()===1,"待补信息缺失");
	check(await page.locator(".report").count()===0,"失败不得显示成功报告");
	check((await page.locator(".execution-panel").innerText()).includes("检索知识资料"),"工具名未翻译");
	await page.getByRole("tab",{name:"证据 2",exact:true}).click();
	check(await page.locator(".evidence-row").count()===2,"同一次检索的两个片段必须保留");
	await page.locator(".evidence-row").first().click();
	const dialog=page.getByRole("dialog");
	await dialog.waitFor();
	check((await dialog.innerText()).includes("不是本次故障的现场观测"),"参考边界未说明");
	check((await dialog.locator(".knowledge-snapshot").innerText()).includes("<script>"),"原文应完整作为纯文本展示");
	check(await dialog.locator("script,a").count()===0,"不能把来源或原文作为可执行内容");
	check((await dialog.innerText()).includes("version-at-run"),"必须保留运行时版本");
	await page.setViewportSize({width:390,height:844});
	check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"窄屏页面溢出");
	check(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth),"长原文导致抽屉溢出");
	await page.keyboard.press("Escape");
	await dialog.waitFor({state:"hidden"});
	await page.waitForFunction(()=>document.querySelector(".evidence-row")===document.activeElement);
	await page.setViewportSize({width:1440,height:1000});
	await page.getByRole("button",{name:"运行历史",exact:true}).click();
	await page.getByRole("button",{name:`打开 ${result.run_id}`}).waitFor();
	check((await page.locator("tbody").innerText()).includes("证据不足"),"历史未区分证据不足");
	await page.getByRole("button",{name:`打开 ${result.run_id}`}).click();
	await page.getByRole("heading",{name:"证据不足，需补充信息",exact:true}).waitFor();
	await page.reload();
	await page.getByRole("heading",{name:"证据不足，需补充信息",exact:true}).waitFor();
	check(errors.length===0,`浏览器异常：${errors.join("; ")}`);
	return {passed:true,mode:"isolated-contract-fixture",checks:["failure-details","two-chunks","tool-timeline","plain-text","snapshot-version","mobile","escape-focus","history","reload","no-page-errors"]};
}
