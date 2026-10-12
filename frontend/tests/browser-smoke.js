async(page)=>{ // 由 Playwright CLI 执行，连接真实 Next.js 与隔离 FastAPI。
	const check=(value,message)=>{if(!value){throw new Error(message);}}; // 每个验收条件失败即停止。
	const errors=[];page.on("pageerror",error=>errors.push(error.message)); // 收集浏览器运行错误。
	await page.setViewportSize({width:1440,height:1000}); // 桌面完整布局。
	await page.goto("http://127.0.0.1:3011/"); // 初始工作台。
	await page.getByRole("heading",{name:"诊断工作台"}).waitFor(); // 确认页面水合完成。
	check(await page.getByRole("button",{name:"开始诊断",exact:true}).isDisabled(),"空输入必须禁止提交"); // 输入校验。
	await page.screenshot({path:"output/playwright/workspace-desktop.png",fullPage:true}); // 保存首屏视觉证据。
	await page.getByRole("button",{name:"RPC 超时示例"}).click(); // 使用仓库真实样本。
	await page.getByRole("button",{name:"开始诊断",exact:true}).click(); // 创建唯一诊断。
	await page.locator(".report").waitFor({timeout:20000}); // 等待真实终止报告。
	check(await page.locator(".status-badge.succeeded").count()===1,"成功状态必须来自后端"); // 不凭连接结束判断。
	check(await page.locator(".execution-panel .trace-item").count()===5,"两轮模型和三个工具应各有记录"); // 并行工具身份完整。
	await page.locator(".citation").first().click(); // 引用必须打开实际证据。
	await page.getByRole("dialog").waitFor(); // 抽屉有可访问语义。
	check((await page.locator(".evidence-summary").innerText()).includes("日志查询匹配2条"),"日志引用须匹配实际证据摘要"); // 校验引用内容。
	await page.screenshot({path:"output/playwright/report-evidence.png",fullPage:true}); // 保存报告与证据关联。
	await page.getByRole("button",{name:"关闭证据"}).click(); // 关闭后焦点返回引用。
	const run_id=(await page.locator(".run-id").innerText()).trim(); // 保留实际 Run ID。
	await page.getByRole("tab",{name:"证据 3",exact:true}).click(); // 三条真实证据。
	check(await page.locator(".evidence-row").count()===3,"不能丢失证据"); // 完整归档验收。
	await page.getByRole("tab",{name:"执行轨迹",exact:true}).click(); // 可回查参数。
	await page.locator("#detail-panel .trace-item").nth(1).locator("summary").click(); // 打开工具详情。
	check((await page.locator("#detail-panel").innerText()).includes("service_name"),"归档后应提供真实查询参数"); // 不生成假参数。
	await page.getByRole("button",{name:"运行历史",exact:true}).click(); // 查询数据库档案。
	await page.locator("tbody tr").first().waitFor(); // 等待真实分页。
	await page.getByRole("textbox",{name:"搜索诊断"}).fill(run_id); // 按身份搜索。
	await page.getByRole("button",{name:"搜索",exact:true}).click(); // 显式提交过滤。
	await page.getByRole("button",{name:`打开 ${run_id}`}).waitFor(); // 搜索结果可打开。
	await page.getByRole("button",{name:`打开 ${run_id}`}).click(); // 只读回查。
	await page.locator(".report").waitFor(); // 原报告恢复。
	await page.reload(); // URL 刷新不创建新 Run。
	await page.locator(".report").waitFor(); // 重新加载持久化报告。
	check((await page.locator(".run-id").innerText()).trim()===run_id,"刷新必须保留相同 Run"); // 身份不可变化。
	await page.screenshot({path:"output/playwright/report-desktop.png",fullPage:true}); // 报告页面视觉验收。
	await page.getByRole("button",{name:"评测结果",exact:true}).click(); // 已实现只读评测。
	await page.getByLabel("选择评测 JSON").setInputFiles("frontend/tests/fixtures/evaluation-mock.json"); // 导入真实离线文件。
	await page.locator(".eval-summary").waitFor(); // 文件校验通过。
	check(await page.locator(".eval-cases details").count()===20,"必须保留全部20条案例"); // 完整案例验收。
	await page.screenshot({path:"output/playwright/evaluation-desktop.png",fullPage:true}); // 评测视图截图。
	await page.getByRole("button",{name:"新建诊断",exact:true}).click(); // 前一次运行已经终止。
	await page.setViewportSize({width:390,height:844}); // 常见手机宽度。
	await page.getByRole("heading",{name:"诊断工作台"}).waitFor(); // 初始页仍可用。
	check(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),"手机页面不得横向溢出"); // 布局边界。
	await page.screenshot({path:"output/playwright/workspace-mobile.png",fullPage:true}); // 手机视觉证据。
	check(errors.length===0,`浏览器异常：${errors.join("; ")}`); // 不能只看页面能打开。
	return {passed:true,run_id,checks:["empty-input","diagnosis","three-evidences","five-executions","citations","history","refresh","evaluation-import","mobile","browser-errors"]}; // 返回可核对验收结果。
} // 结束浏览器成功链。
