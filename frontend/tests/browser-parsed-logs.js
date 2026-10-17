// 隔离接口验证日志证据、来源辅助输入和历史回放；不创建正式 Run。
async(page,artifact_directory="output/playwright")=>{
	const check=(condition,message)=>{if(!condition){throw new Error(message);}};
	const errors=[];page.on("pageerror",error=>errors.push(error.message));
	const timestamp="2026-10-17T08:00:00Z";
	const event={event_index:1,line_start:17,line_end:17,raw_text:'rpc timeout <script>window.log_injected=true</script> '+"长日志".repeat(120),raw_time:"1017 15:00:00",timestamp:null,format:"unknown",level:"error",message:"rpc timeout",code_file:"rpc.cc",code_line:99,warnings:["unrecognized log format"],attributes:{errcode:0}};
	let snapshot={schema_version:"log-evidence-v1",source_id:"rpc-server",source_role:"server",parser_status:"partial",statistics:{event_count:3,unrecognized_count:1,warning_count:1,stop_reason:"event_limit",stopped_early:true},events:[event],selection:{rule:"input_order",keyword:null,limit:10,selected_count:1,omitted_count:2},input_sha256:"input-sha",hash_basis:"full_adapter_input_snapshot_bytes",imported_at:timestamp};
	let malformed=false;
	let capability_mode="ready";
	const evidence=()=>({evidence_id:"logs-1",source:"log",summary:"受控日志证据组",observed_at:timestamp,source_ref:"parsed-log:rpc-server",content_hash:"snapshot-sha",source_version:"log-evidence-v1",content_snapshot:malformed?"<img src=x onerror=alert(1)>":JSON.stringify(snapshot),source_metadata:{observed_at_basis:"import_time"}});
	const result=()=>({run_id:"handoff-logs",request_id:"req",description:"核对受控日志中的 RPC 超时",status:"failed",error_code:"EVIDENCE_INSUFFICIENT",created_at:timestamp,started_at:timestamp,finished_at:timestamp,evidences:[evidence()],report:null,execution_records:[]});
	await page.route("**/api/backend/**",async route=>{
		const path=new URL(route.request().url()).pathname;
		if(path.endsWith("/capabilities")){await route.fulfill(capability_mode==="failed"?{status:503,json:{message:"暂不可用"}}:{json:{persistence:true,provider_mode:"mock",parsed_logs:capability_mode==="ready",parsed_log_sources:capability_mode==="ready"?["rpc-server"]:[]}});}
		else if(path.endsWith("/setup/status")){await route.fulfill({json:{supported:false}});}
		else if(path.endsWith("/events/stream")){const value={event:"run_failed",sequence:1,run_id:"handoff-logs",occurred_at:timestamp,data:{result:result()}};await route.fulfill({contentType:"text/event-stream",body:`event: run_failed\ndata: ${JSON.stringify(value)}\n\n`});}
		else if(path.endsWith("/runs/handoff-logs")){await route.fulfill({json:result()});}
		else if(path.endsWith("/runs")){await route.fulfill({json:{items:[result()],has_more:false}});}
		else{await route.fulfill({status:503,json:{message:"隔离测试未接通"}});}
	});
	await page.setViewportSize({width:1440,height:1000});
	await page.goto("http://127.0.0.1:3011/");
	await page.getByRole("textbox",{name:"故障描述",exact:true}).fill("原有故障上下文");
	await page.getByRole("button",{name:"rpc-server",exact:true}).click();
	check(await page.getByRole("textbox",{name:"故障描述",exact:true}).inputValue()==="原有故障上下文","来源选择不得改变正文");
	check(await page.getByRole("button",{name:"rpc-server",exact:true}).getAttribute("aria-pressed")==="true","来源未选中");
	await page.getByRole("button",{name:"rpc-server",exact:true}).click();
	check(await page.getByRole("button",{name:"rpc-server",exact:true}).getAttribute("aria-pressed")==="false","来源不能取消");
	for(const entry of ["example","file"]){
		await page.getByRole("textbox",{name:"故障描述",exact:true}).fill("???");
		check(await page.getByRole("button",{name:"开始诊断",exact:true}).isDisabled(),"符号输入应禁用");
		if(entry==="example"){await page.getByRole("button",{name:"RPC 超时示例",exact:true}).click();}
		else{await page.getByLabel("选择文本文件",{exact:true}).setInputFiles({name:"error.log",mimeType:"text/plain",buffer:Buffer.from("ERROR connection refused")});}
		check(!await page.getByRole("button",{name:"开始诊断",exact:true}).isDisabled(),`${entry} 填入后旧校验仍阻断发送`);
		check(await page.getByRole("textbox",{name:"故障描述",exact:true}).getAttribute("aria-invalid")==="false","错误状态未清理");
	}
	await page.getByRole("textbox",{name:"故障描述",exact:true}).fill("???");
	await page.getByRole("button",{name:"新建诊断",exact:true}).click();
	check(await page.getByRole("textbox",{name:"故障描述",exact:true}).inputValue()==="","新建未清空");
	check(await page.getByRole("textbox",{name:"故障描述",exact:true}).getAttribute("aria-invalid")==="false","新建未清理校验");
	await page.getByRole("textbox",{name:"故障描述",exact:true}).fill("核对日志连接失败");
	await page.getByRole("button",{name:"rpc-server",exact:true}).click();
	let submitted;
	await page.route("**/api/diagnosis",async route=>{submitted=route.request().postDataJSON();await route.fulfill({status:422,json:{message:"隔离验收：只检查请求，不创建运行"}});});
	const submitted_response=page.waitForResponse(response=>response.url().endsWith("/api/diagnosis"));
	await page.getByRole("button",{name:"开始诊断",exact:true}).click();
	await submitted_response;
	check(JSON.stringify(submitted).includes("已注册日志来源 ID"),"提交未携带选择来源");
	check(!JSON.stringify(submitted).includes("source_ids"),"不得新增诊断请求字段");
	await page.screenshot({path:`${artifact_directory}/parsed-logs-workspace.png`,animations:"disabled"});
	await page.goto("http://127.0.0.1:3011/?run=handoff-logs");
	await page.getByRole("tab",{name:"证据 1",exact:true}).click();
	await page.locator(".evidence-row").click();
	const dialog=page.getByRole("dialog");await dialog.waitFor();
	const text=await dialog.innerText();
	for(const expected of ["扫描不完整","达到事件数量上限","2 条已解析事件未进入","输入行 17","事件时间未知","导入观测时间（非事件时间）","整组日志"]){check(text.includes(expected),`缺少 ${expected}`);}
	check((await page.locator(".log-original").innerText()).includes("<script>"),"原文必须保留");
	check(await dialog.locator("script,img").count()===0,"不可信正文被执行");
	await page.getByRole("searchbox",{name:"查找本组原文"}).fill("不存在的内容");
	await page.getByText("本组没有匹配原文。请修改查找内容。",{exact:true}).waitFor();
	await page.getByRole("searchbox",{name:"查找本组原文"}).fill("");
	await page.screenshot({path:`${artifact_directory}/parsed-logs-desktop.png`,animations:"disabled"});
	await page.setViewportSize({width:390,height:844});
	check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"窄屏页面溢出");
	check(await dialog.evaluate(element=>element.scrollWidth<=element.clientWidth),"窄屏抽屉溢出");
	await page.screenshot({path:`${artifact_directory}/parsed-logs-mobile.png`,animations:"disabled"});
	await page.keyboard.press("Escape");await dialog.waitFor({state:"hidden"});
	await page.waitForFunction(()=>document.activeElement?.classList.contains("evidence-row"));
	await page.reload();await page.getByRole("tab",{name:"证据 1",exact:true}).click();await page.locator(".evidence-row").click();
	check((await dialog.innerText()).includes("输入行 17"),"刷新未恢复归档快照");
	await page.keyboard.press("Escape");
	snapshot={...snapshot,events:[],selection:{...snapshot.selection,selected_count:0,omitted_count:3}};
	await page.reload();await page.getByRole("tab",{name:"证据 1",exact:true}).click();await page.locator(".evidence-row").click();
	await page.getByText("本次选择没有返回事件，不能据此判断服务没有问题。",{exact:true}).waitFor();
	await page.keyboard.press("Escape");malformed=true;
	await page.reload();await page.getByRole("tab",{name:"证据 1",exact:true}).click();await page.locator(".evidence-row").click();
	check((await page.locator(".log-raw-fallback").innerText()).includes("<img"),"损坏快照未降级原文");
	check(await dialog.locator("img").count()===0,"降级原文被执行");
	capability_mode="disabled";await page.goto("http://127.0.0.1:3011/");
	await page.getByText("未启用解析引擎",{exact:true}).waitFor();
	check(await page.getByRole("button",{name:"rpc-server",exact:true}).count()===0,"未启用不得选择来源");
	capability_mode="failed";await page.reload();
	await page.getByRole("button",{name:"重试读取日志来源",exact:true}).waitFor();
	capability_mode="ready";await page.getByRole("button",{name:"重试读取日志来源",exact:true}).click();
	await page.getByRole("button",{name:"rpc-server",exact:true}).waitFor();
	check(errors.length===0,`浏览器异常 ${errors.join(";")}`);
	return {passed:true,checks:["source-tags","source-submit","invalid-to-example","invalid-to-import","new-run-clears-error","partial","omitted","unknown-time","plain-text","local-search","mobile","escape-focus","history-reload","empty","malformed","disabled","capability-retry"]};
}
