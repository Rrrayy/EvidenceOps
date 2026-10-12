async(page)=>{ // 验收真实前端与隔离模型管理 API，不调用真实供应商。
	const check=(value,message)=>{if(!value){throw new Error(message);}}; // 条件失败即停止。
	const errors=[];page.on("pageerror",error=>errors.push(error.message)); // 收集 JS 异常。
	await page.setViewportSize({width:1440,height:1000}); // 桌面布局。
	await page.goto("http://127.0.0.1:3011/?view=connections"); // 真连接设置页。
	await page.getByRole("heading",{name:"模型连接",exact:true}).waitFor(); // 等待水合。
	await page.getByRole("button",{name:"添加模型连接",exact:true}).first().waitFor(); // 服务列表加载。
	await page.getByRole("button",{name:"添加模型连接",exact:true}).first().click(); // 分步添加。
	await page.getByRole("button",{name:"自定义兼容服务 Chat Completions"}).click(); // 后端服务预设。
	await page.getByRole("button",{name:"下一步",exact:true}).click(); // 连接信息。
	const name=`浏览器验收连接-${Date.now()}`; // 每次独立命名。
	await page.getByLabel("连接名称",{exact:true}).fill(name); // 用户自定义连接名。
	await page.getByLabel("API Key",{exact:true}).fill("test-only-secret"); // 仅测试密钥。
	await page.getByRole("button",{name:"显示密钥",exact:true}).click(); // 显示隐藏可用。
	check(await page.getByLabel("API Key",{exact:true}).getAttribute("type")==="text","密钥显示按钮必须可用"); // 密码切换。
	await page.getByRole("button",{name:"隐藏密钥",exact:true}).click(); // 截图前恢复掩码。
	await page.getByLabel("接口地址",{exact:true}).fill("https://models.example/v1"); // 隔离服务域名。
	await page.getByRole("button",{name:"下一步",exact:true}).click(); // 模型手填。
	await page.getByRole("combobox",{name:"模型 ID",exact:true}).fill("agent-model"); // 无目录也可手填。
	await page.getByRole("button",{name:"下一步",exact:true}).click(); // 四项验证。
	await page.getByRole("button",{name:"保存配置并验证模型",exact:true}).click(); // 真保存和协议验证。
	await page.getByText("连接成功，Agent 能力通过",{exact:true}).waitFor(); // 由真实 API 返回。
	check(await page.getByText("已通过",{exact:true}).count()===4,"四项能力应真实通过"); // 认证/调用/工具关联/报告。
	await page.screenshot({path:"output/playwright/model-connection-ready.png",fullPage:true}); // 已接通抽屉。
	await page.getByRole("button",{name:"保存连接",exact:true}).click(); // 保留验证结果并关闭。
	await page.getByRole("dialog").waitFor({state:"hidden"}); // 正常保存生命周期。
	let row=page.locator(".connection-row").filter({hasText:name}); // 精确定位新连接。
	await row.getByText("验证通过",{exact:true}).waitFor(); // 真列表状态。
	await row.getByRole("button",{name:"编辑 / 验证",exact:true}).click(); // 编辑不能回读密钥。
	await page.getByText("密钥已配置",{exact:true}).waitFor(); // 不把掩码作为值。
	check(await page.locator('input[type="password"]').count()===0,"编辑不能回填密钥"); // 密钥读取边界。
	await page.getByRole("button",{name:"保存配置并刷新模型列表",exact:true}).click(); // 显式目录读取。
	await page.getByText(/接口目录 ·/).waitFor(); // 来源及时间。
	await page.getByRole("combobox",{name:"模型 ID",exact:true}).fill("long"); // 输入仅过滤目录。
	await page.keyboard.press("ArrowDown");await page.keyboard.press("Enter"); // 键盘选择长模型。
	check((await page.getByRole("combobox",{name:"模型 ID",exact:true}).inputValue()).includes("long-agent-model"),"加载目录需支持键盘选择"); // 目录不随输入丢失。
	await page.getByRole("button",{name:"关闭连接表单",exact:true}).click(); // 未保存保护。
	await page.getByText("放弃未保存的连接信息？",{exact:true}).waitFor(); // 不自动丢草稿。
	await page.getByRole("button",{name:"放弃并关闭",exact:true}).click(); // 确认丢弃。
	row=page.locator(".connection-row").filter({hasText:name}); // 列表不受草稿修改影响。
	await row.getByRole("button",{name:"设为默认",exact:true}).click(); // 独立默认操作。
	await row.getByText("默认",{exact:true}).waitFor(); // 真默认返回。
	const configured=await page.request.get("http://127.0.0.1:3011/api/backend/model-connections");const entries=await configured.json(); // 读取安全公开响应。
	const item=entries.items.find(value=>value.name===name); // 稳定 ID。
	check(!JSON.stringify(entries).includes("test-only-secret"),"读取响应不得返回密钥"); // 没有凭据。
	await page.request.put("http://127.0.0.1:3011/api/backend/model-connections/default",{data:{connection_id:"system",model_id:entries.system.default_model}}); // 恢复系统全局默认供临时选择验证。
	await page.getByRole("button",{name:"诊断工作台",exact:true}).click(); // 工作台选择本次模型。
	await page.locator(".model-selector").click(); // 轻量选择器。
	await page.getByRole("button").filter({hasText:name}).filter({hasText:"Agent 能力已验证"}).click(); // 选择已验证模型。
	await page.getByRole("textbox",{name:"故障描述",exact:true}).fill("检查订单服务的超时证据"); // 一次诊断。
	await page.getByRole("button",{name:"开始诊断",exact:true}).click(); // 提交明确连接与版本。
	await page.locator(".report").waitFor({timeout:20000}); // 真实后端运行与归档。
	const run_id=(await page.locator(".run-id").innerText()).trim(); // Run 身份。
	await page.getByText("本次模型配置",{exact:true}).click(); // 快照展示。
	check((await page.locator(".submitted-input").first().innerText()).includes(name),"结果须展示本次连接快照"); // 不用现有默认。
	const defaults=await (await page.request.get("http://127.0.0.1:3011/api/backend/model-connections")).json(); // 再读默认。
	check(defaults.default.connection_id==="system","工作台临时选择不能改全局默认"); // 默认隔离。
	await page.reload();await page.locator(".report").waitFor(); // 历史档案固定。
	check((await page.locator(".run-id").innerText()).trim()===run_id,"刷新不能新建 Run"); // 同一历史。
	const storage=await page.evaluate(()=>({local:JSON.stringify(localStorage),session:JSON.stringify(sessionStorage),url:location.href})); // 浏览器持久存储边界。
	check(!JSON.stringify(storage).includes("test-only-secret"),"密钥不能进入存储或 URL"); // 无密钥持久化。
	await page.getByRole("button",{name:"设置 · 模型连接",exact:true}).click(); // 手机管理。
	await page.setViewportSize({width:390,height:844}); // 窄屏。
	await page.locator(".connection-row").filter({hasText:name}).waitFor(); // 列表完成加载。
	check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"手机连接页不能横向溢出"); // 长模型边界。
	await page.screenshot({path:"output/playwright/model-connections-mobile-ready.png",fullPage:true}); // 视觉验收。
	await page.setViewportSize({width:1440,height:1000}); // 删除清理。
	await page.locator(".connection-row").filter({hasText:name}).getByRole("button",{name:"删除",exact:true}).click(); // 删除确认。
	await page.getByRole("button",{name:"确认删除",exact:true}).click(); // 不擅自取消运行。
	await page.locator(".connection-row").filter({hasText:name}).waitFor({state:"hidden"}); // 真删除成功。
	const history=await (await page.request.get(`http://127.0.0.1:3011/api/backend/runs/${run_id}`)).json(); // 删除后历史仍有模型快照。
	check(history.model_config.connection_name===name,"删除连接不能删除历史快照"); // 可追溯。
	await page.route("**/api/backend/model-connections",route=>route.fulfill({status:503,contentType:"application/json",body:'{"message":"测试读取失败"}'})); // 加载失败不伪装空列表。
	await page.getByRole("button",{name:"诊断工作台",exact:true}).click();await page.getByRole("button",{name:"设置 · 模型连接",exact:true}).click(); // 重新读取。
	await page.getByRole("alert").filter({hasText:"测试读取失败"}).waitFor(); // 正式失败反馈。
	await page.unroute("**/api/backend/model-connections");await page.getByRole("button",{name:"重试",exact:true}).click(); // 用户明确重试。
	await page.getByText("系统连接（Mock 演示）",{exact:true}).waitFor(); // 恢复真实列表。
	check(errors.length===0,`浏览器异常：${errors.join(",")}`); // 不忽略 JS 错误。
	return {passed:true,checks:["key-input","encrypted-save","four-capabilities","model-catalog","keyboard-search","unsaved-guard","default-isolation","selected-diagnosis","run-snapshot","history-after-delete","no-browser-secret-storage","mobile","load-failure-retry"]}; // 可核对验收结果。
} // 结束浏览器验收。
