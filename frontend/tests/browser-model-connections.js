async(page)=>{ // 验收真实前端与隔离模型管理 API，不调用真实供应商。
	const check=(value,message)=>{if(!value){throw new Error(message);}}; // 条件失败即停止。
	const errors=[];page.on("pageerror",error=>errors.push(error.message)); // 收集 JS 异常。
	page.on("dialog",dialog=>dialog.type==="beforeunload"?dialog.accept():dialog.dismiss()); // 隔离页面可按用例继续导航。
	await page.setViewportSize({width:1440,height:1000}); // 桌面布局。
	await page.goto("http://127.0.0.1:3011/?view=connections"); // 真连接设置页。
	const initial=await (await page.request.get("http://127.0.0.1:3011/api/backend/model-connections")).json();
	await page.request.put("http://127.0.0.1:3011/api/backend/model-connections/default",{data:{connection_id:"system",model_id:initial.system.default_model}});
	for(const stale of initial.items.filter(value=>value.name.startsWith("浏览器验收连接-"))){await page.request.delete(`http://127.0.0.1:3011/api/backend/model-connections/${stale.id}`,{data:{expected_version:stale.config_version,replacement_id:null}});}
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
	const configured=await page.request.get("http://127.0.0.1:3011/api/backend/model-connections");const entries=await configured.json(); // 读取安全公开响应。
	const item=entries.items.find(value=>value.name===name); // 稳定 ID。
	check(Boolean(item),"已验证连接应出现在管理 API");
	await row.getByRole("button",{name:"编辑 / 验证",exact:true}).click(); // 编辑不能回读密钥。
	await page.getByText("密钥已配置",{exact:true}).waitFor(); // 不把掩码作为值。
	check(await page.locator('input[type="password"]').count()===0,"编辑不能回填密钥"); // 密钥读取边界。
	await page.getByRole("button",{name:"保存配置并刷新模型列表",exact:true}).click(); // 显式目录读取。
	await page.getByText(/接口目录 ·/).waitFor(); // 来源及时间。
	await page.getByText("高级设置",{exact:true}).click(); // 打开容量和超时配置。
	await page.getByRole("combobox",{name:"模型 ID",exact:true}).fill("long"); // 输入仅过滤目录。
	await page.keyboard.press("ArrowDown");await page.keyboard.press("Enter"); // 键盘选择长模型。
	check((await page.getByRole("combobox",{name:"模型 ID",exact:true}).inputValue()).includes("long-agent-model"),"加载目录需支持键盘选择"); // 目录不随输入丢失。
	await page.getByRole("combobox",{name:"模型 ID",exact:true}).fill(item.default_model); // 容量保存不改变已验证模型。
	let oversized_patches=0;await page.route(`**/api/backend/model-connections/${item.id}`,async route=>{if(route.request().method()==="PATCH") oversized_patches++;await route.continue();});
	await page.getByLabel("上下文窗口 Token",{exact:true}).fill("10000001");
	await page.getByRole("dialog").getByRole("button",{name:"保存连接",exact:true}).click();
	await page.getByText("上下文窗口不能超过 10,000,000 Token",{exact:true}).waitFor();
	check(oversized_patches===0,"超出后端 Token 上限不能提交");
	await page.getByLabel("上下文窗口 Token",{exact:true}).fill("");
	await page.unroute(`**/api/backend/model-connections/${item.id}`);
	await page.getByLabel("上下文窗口 Token",{exact:true}).fill("65536"); // 编辑时可设置上下文预算。
	await page.getByLabel("单次输出上限 Token",{exact:true}).fill("4096"); // 输出受上下文约束。
	await page.getByLabel("上下文安全余量 Token",{exact:true}).fill("512"); // 保留安全余量。
	await page.getByLabel("单次诊断预算 Token",{exact:true}).fill("24000"); // Run 累计上限。
	let release_catalog;const hold_catalog=new Promise(resolve=>{release_catalog=resolve;});
	await page.route(`**/api/backend/model-connections/${item.id}/catalog`,async route=>{await hold_catalog;await route.continue();});
	const save_response=page.waitForResponse(response=>response.url().endsWith(`/api/backend/model-connections/${item.id}`)&&response.request().method()==="PATCH");
	const catalog_request=page.waitForRequest(request=>request.url().endsWith(`/api/backend/model-connections/${item.id}/catalog`));
	await page.getByRole("button",{name:"保存配置并刷新模型列表",exact:true}).click();
	await catalog_request;
	await page.waitForFunction(()=>document.getElementById("context-window")?.disabled===true);
	check(await page.getByLabel("上下文窗口 Token",{exact:true}).isDisabled(),"token-inputs-locked-during-request");
	const saved=await save_response;check(saved.ok(),"token-limits-save");
	const saved_body=saved.request().postDataJSON();
	check(saved_body.context_window_tokens===65536&&saved_body.max_output_tokens===4096&&saved_body.safety_margin_tokens===512&&saved_body.max_run_tokens===24000,"token-limits-persisted");
	release_catalog();
	await page.waitForResponse(response=>response.url().endsWith(`/api/backend/model-connections/${item.id}/catalog`));
	await page.unroute(`**/api/backend/model-connections/${item.id}/catalog`);
	await page.getByRole("button",{name:"保存连接",exact:true}).click();
	await page.getByRole("dialog").waitFor({state:"hidden"});
	row=page.locator(".connection-row").filter({hasText:name});await row.getByRole("button",{name:"编辑 / 验证",exact:true}).click();
	await page.getByText("高级设置",{exact:true}).click();
	check(await page.getByLabel("上下文窗口 Token",{exact:true}).inputValue()==="65536","token-limits-reloaded");
	await page.getByLabel("上下文窗口 Token",{exact:true}).fill("");
	const preserve_response=page.waitForResponse(response=>response.url().endsWith(`/api/backend/model-connections/${item.id}`)&&response.request().method()==="PATCH");
	await page.getByRole("button",{name:"保存连接",exact:true}).click();
	const preserved=await preserve_response;check(preserved.ok(),"blank-token-setting-preserves-existing");
	check(preserved.request().postDataJSON().context_window_tokens===undefined,"blank-token-field-omitted");
	await page.getByRole("dialog").waitFor({state:"hidden"});
	row=page.locator(".connection-row").filter({hasText:name});await row.getByRole("button",{name:"编辑 / 验证",exact:true}).click();
	await page.getByText("高级设置",{exact:true}).click();
	check(await page.getByLabel("上下文窗口 Token",{exact:true}).inputValue()==="65536","blank-token-setting-keeps-value");
	await page.getByLabel("超时时间（秒）",{exact:true}).fill("62");
	await page.getByRole("button",{name:"关闭连接表单",exact:true}).click(); // 未保存保护。
	await page.getByText("放弃未保存的连接信息？",{exact:true}).waitFor(); // 不自动丢草稿。
	await page.getByRole("button",{name:"放弃并关闭",exact:true}).click(); // 确认丢弃。
	row=page.locator(".connection-row").filter({hasText:name}); // 列表不受草稿修改影响。
	await row.getByRole("button",{name:"设为默认",exact:true}).click(); // 独立默认操作。
	await row.getByText("默认",{exact:true}).waitFor(); // 真默认返回。
	check(!JSON.stringify(entries).includes("test-only-secret"),"读取响应不得返回密钥"); // 没有凭据。
	await page.request.put("http://127.0.0.1:3011/api/backend/model-connections/default",{data:{connection_id:"system",model_id:entries.system.default_model}}); // 恢复系统全局默认供临时选择验证。
	await page.getByRole("button",{name:"诊断工作台",exact:true}).click(); // 工作台选择本次模型。
	await page.locator(".model-selector").click(); // 轻量选择器。
	await page.locator(".selector-option").filter({hasText:name}).filter({hasText:"Agent 能力已验证"}).click(); // 选择已验证模型。
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
	return {passed:true,checks:["key-input","encrypted-save","four-capabilities","model-catalog","keyboard-search","token-limits-ui-rejects-overflow","token-limits-save-reload","token-inputs-locked-during-request","blank-token-setting-preserves-existing","unsaved-guard","default-isolation","selected-diagnosis","run-snapshot","history-after-delete","no-browser-secret-storage","mobile","load-failure-retry"]}; // 可核对验收结果。
} // 结束浏览器验收。
