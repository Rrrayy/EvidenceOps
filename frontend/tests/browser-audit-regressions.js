// 负责评测竞态、统计真实性和跨页面存储维护的浏览器回归。
async(page)=>{
	const storage_web=Number(process.env.EVIDENCEOPS_STORAGE_FRONTEND_PORT||3015);
	const findings=[];
	await page.goto("http://127.0.0.1:3011/?view=evaluation");
	const valid=await (await page.request.get("http://127.0.0.1:3011/api/backend/runs")).json();
	const archived=valid.items.find(item=>item.status==="succeeded");
	let release;const hold=new Promise(resolve=>{release=resolve;});
	let handled;const completed=new Promise(resolve=>{handled=resolve;});
	await page.route("**/api/backend/runs/*/events/stream?*",async route=>{await hold;await route.continue();handled();});
	await page.goto(`http://127.0.0.1:3011/?run=${archived.run_id}`);
	await page.locator(".report").waitFor();
	findings.push({case:"archived-replay-no-cancel-action",passed:await page.getByRole("button",{name:"取消诊断",exact:true}).count()===0});
	release();await completed;await page.unroute("**/api/backend/runs/*/events/stream?*");
	await page.goto("http://127.0.0.1:3011/?view=evaluation");
	await page.getByLabel("选择评测 JSON").setInputFiles("frontend/tests/fixtures/evaluation-mock.json");
	await page.locator(".eval-summary").waitFor();
	const original=await page.evaluate(()=>document.querySelector(".eval-batch").textContent);
	await page.evaluate(()=>{const original_text=File.prototype.text;File.prototype.text=async function(){const text=await original_text.call(this);if(this.name==="slow.json"){await new Promise(resolve=>setTimeout(resolve,700));}return text;};});
	const sample={schema_version:1,batch_id:"slow-batch",mode:"mock",summary:{case_count:0,rule_passed_count:0,semantic_review_pending:0,execution_error_count:0},results:[]};
	await page.getByLabel("选择评测 JSON").setInputFiles({name:"slow.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify(sample))});
	await page.getByLabel("选择评测 JSON").setInputFiles({name:"fast.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify({...sample,batch_id:"latest-batch"}))});
	await page.waitForFunction(()=>document.querySelector(".eval-batch")?.textContent.includes("latest-batch"));
	await page.waitForTimeout(850);
	findings.push({case:"evaluation-latest-file-wins",passed:(await page.locator(".eval-batch").innerText()).includes("latest-batch")});
	await page.getByLabel("选择评测 JSON").setInputFiles({name:"forged.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify({...sample,batch_id:"forged-errors",summary:{...sample.summary,execution_error_count:99}}))});
	await page.getByRole("alert").filter({hasText:"执行错误数量与案例不一致"}).waitFor();
	findings.push({case:"evaluation-error-total-consistent",passed:!(await page.locator(".eval-batch").innerText()).includes("forged-errors")});
	await page.goto(`http://127.0.0.1:${storage_web}/?view=storage`);
	await page.getByRole("button",{name:"创建备份",exact:true}).waitFor();
	const response=await page.request.get(`http://127.0.0.1:${storage_web}/api/backend/storage/status`);const status=await response.json();
	const operation={id:"audit-other-tab",action:"backup",status:"running",stage:"backup",message:"另一个页面正在备份",created_at:new Date().toISOString()};
	let polls=0;
	await page.route("**/api/backend/storage/status",route=>route.fulfill({json:{...status,state:"maintenance",operations:[operation]}}));
	await page.route("**/api/backend/storage/operations/audit-other-tab",route=>{polls++;return route.fulfill({json:{...operation,status:"succeeded",message:"另一个页面备份完成"}});});
	await page.getByRole("button",{name:"刷新存储状态",exact:true}).click();
	await page.waitForTimeout(900);
	findings.push({case:"storage-refresh-discovers-operation",passed:polls>0});
	await page.unroute("**/api/backend/storage/status");await page.unroute("**/api/backend/storage/operations/audit-other-tab");
	if(findings.some(item=>!item.passed)){throw new Error(JSON.stringify(findings));}
	return {passed:true,findings,original,isolated_history_count:valid.items.length};
}
