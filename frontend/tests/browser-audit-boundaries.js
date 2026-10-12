// 负责输入边界、重复提交、历史筛选、键盘操作和多尺寸布局验收。
async(page)=>{
	const checks=[];
	const check=(condition,name)=>{if(!condition){throw new Error(name);}checks.push(name);};
	const errors=[];page.on("pageerror",error=>errors.push(error.message));
	await page.setViewportSize({width:1440,height:1000});
	await page.goto("http://127.0.0.1:3011/");
	await page.getByRole("textbox",{name:"故障描述"}).fill("  \n  ");
	check(await page.getByRole("button",{name:"开始诊断",exact:true}).isDisabled(),"whitespace-disabled");
	await page.getByLabel("选择文本文件").setInputFiles({name:"bad.exe",mimeType:"application/octet-stream",buffer:Buffer.from("content")});
	await page.getByRole("alert").filter({hasText:"请选择纯文本"}).waitFor();checks.push("unsupported-text-file");
	await page.getByLabel("选择文本文件").setInputFiles({name:"binary.log",mimeType:"text/plain",buffer:Buffer.from("bad\0content")});
	await page.getByRole("alert").filter({hasText:"文件包含非文本内容"}).waitFor();checks.push("binary-text-rejected");
	await page.getByLabel("选择文本文件").setInputFiles({name:"large.log",mimeType:"text/plain",buffer:Buffer.alloc(300001,65)});
	await page.getByRole("alert").filter({hasText:"不能超过 300 KB"}).waitFor();checks.push("oversized-text-rejected");
	await page.getByLabel("选择文本文件").setInputFiles({name:"source.log",mimeType:"text/plain",buffer:Buffer.from("订单服务 RPC 超时，检查日志")});
	check(await page.getByRole("textbox",{name:"故障描述"}).inputValue()==="订单服务 RPC 超时，检查日志","valid-text-import");
	check(await page.getByRole("alert").filter({hasText:"文本文件不能超过"}).count()===0,"valid-text-clears-import-error");
	await page.getByRole("textbox",{name:"故障描述"}).fill("测试重连重复点击");
	let creations=0;const count=request=>{if(request.method()==="POST"&&request.url().endsWith("/api/diagnosis")){creations++;}};page.on("request",count);
	await page.getByRole("button",{name:"开始诊断",exact:true}).evaluate(element=>{element.click();element.click();});
	await page.getByRole("button",{name:"取消诊断",exact:true}).waitFor();
	check(await page.getByRole("button",{name:"新建诊断",exact:true}).isDisabled(),"active-run-new-disabled");
	await page.getByRole("button",{name:"运行历史",exact:true}).click();
	await page.locator("tbody tr").first().waitFor();
	check(await page.locator('button[aria-label^="打开 run-"]').first().isDisabled(),"active-run-history-disabled");
	await page.getByRole("button",{name:"诊断工作台",exact:true}).click();await page.locator(".report").waitFor();
	check(creations===1,"rapid-double-click-single-run");page.off("request",count);
	await page.getByRole("tab",{name:"诊断报告",exact:true}).focus();await page.keyboard.press("ArrowRight");
	check(await page.getByRole("tab",{name:"证据 3",exact:true}).getAttribute("aria-selected")==="true","tabs-arrow-navigation");
	await page.keyboard.press("End");check(await page.getByRole("tab",{name:"执行轨迹",exact:true}).getAttribute("aria-selected")==="true","tabs-end-navigation");
	await page.keyboard.press("Home");await page.locator(".citation").first().click();await page.getByRole("dialog").waitFor();
	await page.keyboard.press("Escape");await page.getByRole("dialog").waitFor({state:"hidden"});
	check(await page.locator(".citation").first().evaluate(element=>element===document.activeElement),"evidence-focus-restored");
	const report_url=page.url();
	for(let index=0;index<8;index++){
		const response=await page.request.post("http://127.0.0.1:3011/api/diagnosis",{data:{messages:[{role:"user",parts:[{type:"text",text:`分页测试 ${index}`}]}],connection_id:"system"}});
		check(response.ok(),`pagination-seed-${index}`);
	}
	await page.getByRole("button",{name:"运行历史",exact:true}).click();await page.locator("tbody tr").first().waitFor();
	check(await page.locator("tbody tr").count()===12,"history-page-size");
	await page.getByRole("button",{name:"下一页",exact:true}).click();await page.getByText("第 2 页",{exact:true}).waitFor();
	await page.waitForFunction(()=>!document.querySelector('.history-filters input')?.disabled);
	check(await page.locator("tbody tr").count()>0,"history-next-page");
	await page.getByRole("combobox",{name:"筛选运行状态"}).selectOption("failed");
	await page.waitForFunction(()=>!document.querySelector('.history-filters input')?.disabled);
	check((await page.locator("tbody .status-badge").allTextContents()).every(text=>text==="诊断失败"),"history-status-filter");
	await page.getByRole("textbox",{name:"搜索诊断"}).fill("不存在的故障 audit-no-match");await page.getByRole("button",{name:"搜索",exact:true}).click();
	await page.locator(".empty-panel").waitFor();check(await page.locator(".pagination").count()===0,"history-empty-no-pagination");
	await page.goto("http://127.0.0.1:3011/?view=evaluation");
	await page.getByLabel("选择评测 JSON").setInputFiles("frontend/tests/fixtures/evaluation-mock.json");await page.locator(".eval-summary").waitFor();
	await page.getByLabel("选择评测 JSON").setInputFiles({name:"invalid.json",mimeType:"application/json",buffer:Buffer.from("not json")});
	await page.getByRole("alert").filter({hasText:"无法读取评测"}).waitFor();check(await page.locator(".eval-cases details").count()===20,"bad-evaluation-keeps-valid-result");
	await page.getByLabel("选择评测 JSON").setInputFiles({name:"too-large.json",mimeType:"application/json",buffer:Buffer.alloc(10000001,65)});
	await page.getByRole("alert").filter({hasText:"不能超过 10 MB"}).waitFor();checks.push("oversized-evaluation-rejected");
	const layouts=[];
	for(const width of [320,390,768,1024,1440]){
		await page.setViewportSize({width,height:900});
		for(const view of ["workspace","history","evaluation","connections","storage"]){
			const base=view==="storage"?3015:3011;
			await page.goto(view==="workspace"?report_url:`http://127.0.0.1:${base}/?view=${view}`);
			await page.locator("main h1").waitFor();
			await page.waitForTimeout(100);
			const bounds=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
			layouts.push({width,view,...bounds});check(bounds.scroll<=bounds.width,`no-overflow-${view}-${width}`);
			if(view==="history"&&width===320){check(await page.locator("tbody tr").first().evaluate(element=>element.getBoundingClientRect().height<180),"mobile-history-readable-rows");}
			if(width===320||width===1440){await page.screenshot({path:`output/playwright/audit-${view}-${width}.png`,fullPage:true});}
		}
	}
	check(errors.length===0,`browser-runtime-errors ${errors.join(";")}`);
	return {passed:true,checks,layouts};
}
