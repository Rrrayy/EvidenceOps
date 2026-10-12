async(page)=>{ // 验证工具台的能力提示与默认状态，不调用用户模型。
	const check=(value,message)=>{if(!value){throw new Error(message);}}; // 条件失败停止验收。
	const errors=[];page.on("pageerror",error=>errors.push(error.message)); // 收集页面异常。
	await page.setViewportSize({width:1440,height:1000}); // 桌面工作区。
	await page.route("**/api/backend/runs?*",route=>route.fulfill({status:503,json:{error_code:"PERSISTENCE_DISABLED",message:"当前未启用PostgreSQL持久化"}})); // 模拟后端明确关闭历史。
	await page.goto("http://127.0.0.1:3011/?view=history"); // 验证功能不可用状态。
	await page.getByRole("heading",{name:"运行历史尚未启用"}).waitFor(); // 状态必须解释原因。
	check(await page.getByRole("textbox",{name:"搜索诊断"}).isDisabled(),"未启用时搜索必须禁用"); // 不允许无效筛选。
	check(await page.getByRole("combobox",{name:"筛选运行状态"}).isDisabled(),"未启用时筛选必须禁用"); // 状态筛选也不可用。
	check(await page.locator(".pagination").count()===0,"未启用时不展示分页"); // 删除空白分页。
	check(await page.locator(".error-banner").count()===0,"未启用不能表现为读取故障"); // 中性提示与错误分开。
	await page.getByText("如何启用数据库持久化",{exact:true}).click(); // 技术步骤默认折叠。
	check((await page.locator(".persistence-notice").innerText()).includes("EVIDENCEOPS_PERSISTENCE"),"应提供实际启用方式"); // 不提供假网页开关。
	await page.screenshot({path:"output/playwright/history-unavailable-professional.png",fullPage:true}); // 保存能力提示。
	await page.unroute("**/api/backend/runs?*"); // 恢复真实后端。
	await page.route("**/api/backend/runs?*",route=>route.fulfill({status:503,json:{error_code:"DATABASE_UNAVAILABLE",message:"历史服务暂不可用，请重试"}})); // 模拟真正读取故障。
	await page.getByRole("button",{name:"刷新历史"}).click(); // 重新加载能力。
	await page.getByRole("alert").filter({hasText:"历史服务暂不可用"}).waitFor(); // 故障不能伪装未启用。
	check(await page.locator(".persistence-notice").count()===0,"读取故障不能建议开启已开启服务"); // 防止错误分类。
	await page.unroute("**/api/backend/runs?*"); // 恢复 PostgreSQL 历史。
	await page.getByRole("button",{name:"刷新历史"}).click(); // 重试真实数据库。
	await page.locator("tbody tr").first().waitFor(); // 新诊断已保存。
	check(await page.getByRole("textbox",{name:"搜索诊断"}).isEnabled(),"持久化恢复后搜索可用"); // 能力状态可恢复。
	await page.screenshot({path:"output/playwright/history-professional.png",fullPage:true}); // 保存档案列表。
	await page.route("**/api/backend/model-connections",async route=>{ // 只替换浏览器响应中的默认选择。
		const response=await route.fetch(); // 读取脱敏连接信息。
		const listing=await response.json(); // 原接口不返回密钥。
		await route.fulfill({response,json:{...listing,default:null}}); // 无显式默认时使用系统连接。
	});
	await page.goto("http://127.0.0.1:3011/?view=connections"); // 检查系统回退默认。
	await page.locator(".connection-status").getByRole("button",{name:"当前默认",exact:true}).waitFor(); // 不能仍显示设为默认。
	check(await page.locator(".connection-status").getByRole("button",{name:"当前默认",exact:true}).isDisabled(),"当前默认不应重复提交"); // 不发送无效更新。
	check(!(await page.locator(".connection-boundaries").innerText()).includes("Embedding"),"高级说明默认折叠"); // 首次使用降低技术负担。
	await page.getByText("高级说明",{exact:true}).click(); // 按需查看用途边界。
	check((await page.locator(".connection-boundaries").innerText()).includes("Embedding"),"高级说明必须保留用途边界"); // 不误导全部 AI 配置一起切换。
	await page.screenshot({path:"output/playwright/connections-professional.png",fullPage:true}); // 保存模型列表。
	await page.getByRole("button",{name:"添加模型连接",exact:true}).first().click(); // 不保存任何测试连接。
	await page.getByRole("button",{name:"下一步",exact:true}).click(); // 进入连接表单。
	await page.setViewportSize({width:390,height:844}); // 验证抽屉窄屏。
	check(await page.getByLabel("API Key",{exact:true}).isEditable(),"API Key 应可输入"); // 表单已接通。
	check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"手机页面不能横向溢出"); // 窄屏布局边界。
	await page.screenshot({path:"output/playwright/connection-form-mobile-professional.png",fullPage:true}); // 保存手机表单。
	await page.getByRole("button",{name:"关闭连接表单",exact:true}).click(); // 无修改草稿直接关闭。
	await page.unroute("**/api/backend/model-connections"); // 清理默认值模拟。
	check(errors.length===0,errors.join("; ")); // 无页面异常。
	return {passed:true,checks:["persistence-disabled","search-disabled","pagination-hidden","startup-instructions","failure-retry","postgres-history","system-fallback-default","advanced-copy","key-input","mobile"]}; // 输出验收结果。
}
