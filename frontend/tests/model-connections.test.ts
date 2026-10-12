import {strict as assert} from "node:assert"; // 测试安全边界，不依赖真实供应商。
import {test} from "node:test"; // 沿用已有测试运行器。
import {safe_endpoint,draft_error,connection_labels} from "../src/lib/model-connections"; // 检查实际界面使用的纯函数。
test("接口展示去掉用户信息、路径凭据、查询和片段",()=>{ // 防止地址成为密钥展示通道。
	assert.equal(safe_endpoint("https://account:secret@models.example:8443/private-key?api_key=secret#token"),"https://models.example:8443"); // 只保留 origin。
}); // 结束地址测试。
test("错误地址与不允许的协议不回显原始值",()=>{ // 非 URL 字符串可能含敏感值。
	for(const endpoint of ["secret-key","javascript:secret","file:///private-token"]){assert.equal(safe_endpoint(endpoint),"地址格式无效");} // 错误提示没有输入原文。
}); // 结束异常测试。
test("目录未接通仍允许手动模型 ID，格式检查不表示验证通过",()=>{ // 模型手填不依赖目录。
	assert.equal(draft_error("内部服务","https://models.example/v1","custom-agent-model"),""); // 手填格式通过。
	assert.match(draft_error("内部服务","https://models.example/v1",""),/手动填写/); // 模型缺失有可操作提示。
	assert.match(draft_error("","https://models.example/v1","model"),/连接名称/); // 名称不可为空。
	assert.match(draft_error("内部服务","invalid","model"),/接口地址/); // 地址错误独立反馈。
}); // 结束手填边界。
test("所有验证状态有明确文字",()=>{ // 能力状态不依赖颜色。
	assert.equal(Object.keys(connection_labels).length,6); // 六个规定状态。
	assert.match(connection_labels.stale,/重新验证/); // 修改后不得显示 ready。
}); // 结束状态测试。
