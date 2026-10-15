// 在更新后的测试前端只读回放实际安装的全部历史，不创建或修改正式运行。
async(page)=>{
	const check=(value,message)=>{if(!value){throw new Error(message);}};
	const web_url=new URL(page.url()).origin;
	check(["http://127.0.0.1:3011","http://127.0.0.1:3013"].includes(web_url),"仅允许本机只读验收入口");
	const errors=[];
	page.on("pageerror",error=>errors.push(error.message));
	await page.route("**/api/backend/**",async route=>{
		check(route.request().method()==="GET","真实历史验收禁止写请求");
		const original=new URL(route.request().url());
		original.port="3013";
		const response=await route.fetch({url:original.href});
		await route.fulfill({response});
	});
	const listing=await (await page.request.get("http://127.0.0.1:3013/api/backend/runs?limit=100&offset=0")).json();
	check(!listing.has_more,"历史超过本次验收上限，需要翻页");
	const verified=[];
	for(const item of listing.items){
		await page.goto(`${web_url}/?run=${item.run_id}`);
		await page.locator(".status-badge").filter({hasText:item.status==="succeeded"?"已完成":item.status==="cancelled"?"已取消":item.error_code==="EVIDENCE_INSUFFICIENT"?"证据不足":"诊断失败"}).waitFor();
		await page.waitForFunction(()=>!document.querySelector(".live-indicator")?.textContent.includes("观察中"));
		check(await page.locator(".error-banner[role=alert]").count()===0,`历史读取错误：${item.run_id}`);
		check(await page.getByRole("button",{name:"取消诊断",exact:true}).count()===0,"已终止运行不能显示取消操作");
		check(await page.locator(".report").count()===(item.status==="succeeded"?1:0),`报告与状态不一致：${item.run_id}`);
		verified.push({run_id:item.run_id,status:item.status});
	}
	const identity="run-16276712-4700-4b1c-846c-e6e0d6a45786";
	await page.goto(`${web_url}/?run=${identity}`);
	await page.getByRole("heading",{name:"证据不足，需补充信息",exact:true}).waitFor();
	await page.getByText("本次模型配置",{exact:true}).click();
	const config=await page.locator(".submitted-input").first().innerText();
	check(config.includes("qianwen-platform")&&config.includes("qwen3.8-flash")&&config.includes("未记录"),"验收快照缺失信息必须诚实展示");
	await page.getByRole("tab",{name:"证据 3",exact:true}).click();
	await page.locator(".evidence-row").first().click();
	await page.getByRole("dialog").waitFor();
	check(await page.locator(".knowledge-snapshot").count()===1,"真实知识快照未展示");
	await page.screenshot({path:"output/playwright/real-knowledge-history.png",fullPage:true});
	await page.keyboard.press("Escape");
	check(errors.length===0,`浏览器错误：${errors.join("; ")}`);
	return {passed:true,mode:"read-only-real-archives",count:verified.length,verified};
}
