// 只测试无效请求和已有演示档案，不创建生产运行或调用付费模型。
async (page) => {
	const web_url=process.env.EVIDENCEOPS_TEST_WEB_URL??"http://127.0.0.1:3011";
	const api_url=process.env.EVIDENCEOPS_TEST_API_URL??"http://127.0.0.1:8011";
	let diagnosis_posts=0;
	const observe=(request) => {
		if(request.method()==="POST"&&request.url().endsWith("/api/diagnosis")) diagnosis_posts++;
	};
	page.on("request",observe);
	try {
		await page.goto(`${web_url}/?view=workspace`);
		const input=page.getByRole("textbox",{name:"故障描述",exact:true});
		await input.waitFor();
		for(const text of ["?","？？？","...","🔥"]){
			await input.fill(text);
			await page.getByRole("button",{name:"开始诊断",exact:true}).waitFor();
			if(!await page.getByRole("button",{name:"开始诊断",exact:true}).isDisabled()) throw new Error("无效输入仍可提交");
			await input.press("Control+Enter");
			if(await input.inputValue()!==text) throw new Error("无效输入被清空");
			if(!await page.locator("#diagnosis-input-help").textContent().then(text=>text.includes("不能只输入"))) throw new Error("未显示输入提示");
		}
		if(diagnosis_posts!==0) throw new Error("无效输入调用诊断接口");
		await input.fill("OOM");
		if(await page.getByRole("button",{name:"开始诊断",exact:true}).isDisabled()) throw new Error("有效简短描述被阻断");
		const proxy=await page.request.post(`${web_url}/api/diagnosis`,{data:{messages:[{role:"user",parts:[{type:"text",text:"?"}]}]}});
		if(proxy.status()!==422) throw new Error("代理未拒绝无效输入");
		const history=await page.request.get(`${api_url}/api/v1/agent/runs?limit=100`);
		if(!history.ok()) throw new Error("本测试需要已启用持久化的隔离环境");
		const before=await history.json();
		for(const endpoint of ["diagnosis","diagnosis/stream"]){
			const response=await page.request.post(`${api_url}/api/v1/agent/${endpoint}`,{data:{description:"?"}});
			if(response.status()!==422) throw new Error("后端未拒绝无效输入");
		}
		const after=await page.request.get(`${api_url}/api/v1/agent/runs?limit=100`).then(response=>response.json());
		if(JSON.stringify(before)!==JSON.stringify(after)) throw new Error("无效请求改变历史");
		let mock_label=null;
		for(const item of before.items){
			const result=await page.request.get(`${api_url}/api/v1/agent/runs/${encodeURIComponent(item.run_id)}`).then(response=>response.json());
			if(result.model_config?.provider_id!=="mock"||!result.report) continue;
			await page.goto(`${web_url}/?run=${encodeURIComponent(item.run_id)}`);
			await page.getByText("Mock 演示报告",{exact:true}).waitFor();
			await page.getByText("样例置信度",{exact:false}).waitFor();
			if(!await page.getByText("本次使用 Mock：",{exact:false}).isVisible()) throw new Error("固定演示未说明");
			mock_label=true;
			break;
		}
		return {passed:true,invalid_ui_posts:diagnosis_posts,proxy_status:proxy.status(),history_unchanged:true,mock_label,mock_skip_reason:mock_label?null:"隔离环境没有已完成的 Mock 报告，未验收演示标识"};
	} finally {
		page.off("request",observe);
	}
}
