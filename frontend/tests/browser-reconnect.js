async(page)=>{ // 验证连接中断后自动补发而非重复创建。
	const check=(value,message)=>{if(!value){throw new Error(message);}}; // 条件不满足即失败。
	await page.goto("http://127.0.0.1:3011/"); // 新页面有独立状态。
	let creation_count=0; // 记录真实创建 POST 次数。
	await page.route("**/api/diagnosis",async(route)=>{ // 只切断浏览器接收到的流，服务端仍正常完成。
		creation_count++;const response=await route.fetch();const text=await response.text(); // 实际请求仍由 Next.js 和 FastAPI 执行。
		const first_frame=text.split("\n\n").find((frame)=>frame.includes('"type":"data-run-event"')); // 保留实际 run_started 身份。
		check(Boolean(first_frame),"必须先收到真实运行身份"); // 未知创建结果不能自动恢复。
		await route.fulfill({response,body:`${first_frame}\n\ndata: [DONE]\n\n`}); // 模拟创建连接提前结束。
	}); // 不伪造诊断结论或证据。
	await page.getByRole("textbox",{name:"故障描述"}).fill("测试重连诊断"); // 使用隔离慢供应商。
	await page.getByRole("button",{name:"开始诊断",exact:true}).click(); // 用户只提交一次。
	await page.locator(".report").waitFor({timeout:20000}); // 有界自动恢复应读到最终真实报告。
	check(creation_count===1,"自动恢复不得重发创建 POST"); // 防止重复模型执行。
	check(await page.locator(".execution-panel .trace-item").count()===5,"事件应完整且不重复"); // 去重和补发一致。
	check(await page.locator(".reconnect-banner").count()===0,"恢复后连接警告应消失"); // UI 不保留陈旧故障。
	await page.unroute("**/api/diagnosis"); // 清理故障注入。
	await page.setViewportSize({width:390,height:844}); // 手机完成后仍可操作。
	await page.getByRole("button",{name:"新建诊断",exact:true}).click(); // 手机入口不能被隐藏。
	await page.getByRole("heading",{name:"诊断工作台"}).waitFor(); // 可以开始下一次。
	await page.screenshot({path:"output/playwright/workspace-mobile.png",fullPage:true}); // 保存最终手机布局。
	return {passed:true,checks:["bounded-auto-reconnect","one-creation-post","deduplicated-replay","mobile-new-run"]}; // 可复现结果。
} // 结束自动重连测试。
