async(page)=>{ // 对已经通过测试的页面保存最终稳定视觉状态。
	await page.setViewportSize({width:1440,height:1000}); // 桌面阅读宽度。
	await page.goto("http://127.0.0.1:3011/"); // 回到空工作台供用户查看。
	await page.getByText("持久化已启用",{exact:true}).waitFor(); // 确认能力查询完成，而非截图加载瞬间。
	await page.screenshot({path:"output/playwright/workspace-desktop.png",fullPage:true}); // 保存最终稳定首屏。
	return {ready:true}; // 预览已可查看。
} // 结束视觉留档。
