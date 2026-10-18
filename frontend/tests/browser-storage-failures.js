// 验证存储维护失败、表单保留、历史回滚和错误重试。
async(page)=>{
	const web=Number(process.env.EVIDENCEOPS_STORAGE_FRONTEND_PORT||3015);
	const check=(value,message)=>{if(!value){throw new Error(message);}};
	await page.setViewportSize({width:1440,height:1000});
	await page.goto(`http://127.0.0.1:${web}/?view=storage`);
	await page.getByRole("button",{name:"更改存储方式",exact:true}).waitFor();
	const before=await (await page.request.get(`http://127.0.0.1:${web}/api/backend/runs`)).json();
	await page.getByRole("button",{name:"更改存储方式",exact:true}).click();
	await page.getByLabel("存储方式",{exact:true}).selectOption("postgres");
	await page.getByLabel("端口",{exact:true}).fill("1");
	await page.getByLabel("数据库密码",{exact:true}).fill("test-only-invalid-password");
	await page.getByRole("button",{name:"备份并切换",exact:true}).click();
	await page.getByRole("dialog").getByRole("alert").waitFor({timeout:20000});
	check(await page.getByLabel("端口",{exact:true}).inputValue()==="1","失败必须保留输入");
	check(!(await page.getByRole("dialog").innerText()).includes("test-only-invalid-password"),"错误不得回显密码");
	const after=await (await page.request.get(`http://127.0.0.1:${web}/api/backend/runs`)).json();
	check(JSON.stringify(before.items.map(item=>item.run_id))===JSON.stringify(after.items.map(item=>item.run_id)),"维护失败不能丢失历史");
	await page.evaluate(()=>{window.confirm=()=>true;});
	await page.getByRole("button",{name:"关闭存储表单",exact:true}).click();
	const backup_count=await page.locator("tbody tr").count();
	await page.getByLabel("选择诊断备份",{exact:true}).setInputFiles({name:"corrupted.json",mimeType:"application/json",buffer:Buffer.from('{"payload":null}')});
	await page.getByRole("alert").filter({hasText:"备份格式或内容校验失败"}).waitFor();
	check(await page.locator("tbody tr").count()===backup_count,"损坏文件不能进入列表");
	await page.route("**/api/backend/storage/status",route=>route.fulfill({status:503,json:{message:"测试存储状态读取失败"}}));
	await page.getByRole("button",{name:"刷新存储状态",exact:true}).click();
	await page.getByRole("alert").filter({hasText:"测试存储状态读取失败"}).waitFor();
	await page.unroute("**/api/backend/storage/status");
	await page.getByRole("button",{name:"刷新存储状态",exact:true}).click();
	await page.waitForFunction(()=>!document.querySelector(".error-banner"));
	await page.screenshot({path:"output/playwright/storage-recovered.png",fullPage:true});
	return {passed:true,checks:["target-failure","input-preserved","history-rollback","corrupt-import","status-failure","retry"]};
}
