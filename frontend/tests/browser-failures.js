async(page)=>{ // 真实浏览器故障路径，模型故障只由隔离测试供应商注入。
	const check=(value,message)=>{if(!value){throw new Error(message);}}; // 条件不满足立即失败。
	await page.setViewportSize({width:1440,height:1000}); // 保持按钮都在可见布局。
	await page.goto("http://127.0.0.1:3011/"); // 每条路径从新工作台开始。
	await page.getByRole("textbox",{name:"故障描述"}).fill("测试模型失败"); // 注入供应商超时。
	await page.getByRole("button",{name:"开始诊断",exact:true}).click(); // 创建实际失败 Run。
	await page.locator(".status-badge.failed").waitFor({timeout:20000}); // 业务终态须为 failed。
	check(await page.locator(".report").count()===0,"失败运行不得生成成功报告"); // 不伪造报告。
	check((await page.locator(".no-report").innerText()).includes("测试模型请求超时"),"应提供实际错误原因"); // 失败可定位。
	await page.screenshot({path:"output/playwright/failed-run.png",fullPage:true}); // 保存失败路径。
	await page.getByRole("button",{name:"新建诊断",exact:true}).click(); // 终态后可重新创建。
	await page.getByRole("textbox",{name:"故障描述"}).fill("测试取消诊断"); // 延迟供应商留出取消窗口。
	await page.getByRole("button",{name:"开始诊断",exact:true}).click(); // 开始慢模型。
	await page.getByRole("button",{name:"取消诊断",exact:true}).waitFor(); // Run ID 已确认。
	await page.getByRole("button",{name:"取消诊断",exact:true}).click(); // 显式业务取消。
	await page.locator(".status-badge.cancelled").waitFor({timeout:20000}); // 等待后端提交取消终态。
	check(await page.locator(".report").count()===0,"取消不得保存成功报告"); // 与后端契约一致。
	await page.getByRole("button",{name:"新建诊断",exact:true}).click(); // 隔离下一条运行。
	await page.getByRole("textbox",{name:"故障描述"}).fill("测试重连诊断"); // 创造流中途刷新窗口。
	await page.getByRole("button",{name:"开始诊断",exact:true}).click(); // 创建唯一 Run。
	await page.waitForFunction(()=>new URL(location.href).searchParams.has("run")); // 等待可靠运行身份。
	const reconnect_id=new URL(page.url()).searchParams.get("run"); // 保存原始 Run。
	await page.reload(); // 真实断开 POST 观察连接，不取消后台任务。
	await page.locator(".report").waitFor({timeout:20000}); // GET 历史补发并观察同一个任务。
	check(new URL(page.url()).searchParams.get("run")===reconnect_id,"断线不得创建新 Run"); // 创建次数不增加。
	check(await page.locator(".execution-panel .trace-item").count()===5,"重放不能丢事件或重复卡片"); // 完整轨迹。
	// 保留成功报告，直接查询不存在的 Run，确认不会显示旧结论。
	await page.getByRole("button",{name:"查询运行 ID",exact:true}).click(); // 输入缺失身份。
	await page.getByRole("textbox",{name:"运行 ID",exact:true}).fill("run-does-not-exist"); // 稳定未知 Run。
	await page.getByRole("button",{name:"打开档案",exact:true}).click(); // 查询只能 GET。
	await page.getByRole("alert").filter({hasText:"诊断运行不存在"}).waitFor(); // 404 不是空报告或成功。
	check(await page.locator(".report").count()===0,"未知 Run 不得展示旧报告"); // 防止跨档案内容混淆。
	return {passed:true,checks:["model-timeout","no-fake-report","explicit-cancellation","disconnect-refresh-replay","same-run-identity","missing-run"]}; // 保存故障验收结果。
} // 结束浏览器失败测试。
