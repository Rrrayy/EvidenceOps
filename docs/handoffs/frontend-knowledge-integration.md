# 知识检索结果的前端消费契约

## 后端增量：可选混合检索

服务端可选 hybrid，默认 cosine，接口与 Evidence 身份不变。source_metadata.retrieval_details 为可选对象：score_kind=rrf、rrf_constant、branches（各路 rank/score）、vector_candidates、keyword_candidates。retrieval_method=hybrid-rrf-keyword-v1 的 score 不是相似度或置信度，禁止百分比展示；关键词分支不是 BM25，缺失分支或旧字段要兼容。本批只更新契约，未修改前端源码、配置或测试。后端真实 Embedding 检索对照已完成，不能代替前端端到端和生成质量验收。

前端通过原有诊断、终止 SSE 和运行历史接口消费知识快照。依据 `frontend.md` 顶部的当前有效契约，不新增知识搜索、上传、构建或发布 HTTP 入口，不向浏览器开放服务端文档选择。

## 页面行为

- `source=knowledge` 显示为“知识参考”，与日志、指标和配置观测区分。抽屉展示运行时 `content_snapshot`、标题路径、逻辑来源、内容版本及检索身份。来源按文本展示，不转换为文件链接。
- 报告引用按本 Run 的 `evidence_id` 定位；一次工具调用返回多个片段时，各自保留证据身份。没有报告的失败 Run 仍可在证据页查看快照。
- 正文以 React 文本节点展示，不执行 HTML，不把 Markdown 链接或指令转换为交互。Python 字符范围只展示，不用 JavaScript 索引截取原文。检索评分不作为准确率或置信度。
- `search_knowledge` 在现有时间线显示“检索知识资料”，沿用 `tool_started/tool_finished`。没有收到完整归档前，不从工具事件伪造片段。
- `failed/EVIDENCE_INSUFFICIENT` 显示“证据不足，需补充信息”，展示 `error_detail.message` 和可选的 `missing_information`。普通协议错误保留实际说明；失败或取消结果不渲染成功报告。
- 历史列表将明确的证据不足与其他失败区分，并显示实际保存的失败说明。旧记录缺少新增字段、说明或原文时保持兼容，缺失值标明未记录。
- 前端可接收 `knowledge_search` 能力字段，不将启用工具解释为文档已发布、检索成功或模型已使用知识。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `frontend/src/lib/contracts.ts` | 校验知识快照、来源元数据和可选的待补信息；统一类型与工具名称 |
| `frontend/src/components/knowledge-evidence.tsx` | 只读知识正文及检索元数据 |
| `frontend/src/components/console.tsx` | 证据抽屉组装、按 Run 读取历史；支持 React 开发模式清理后重新观察 |
| `frontend/src/components/report.tsx` | 失败说明、补充清单及报告展示边界 |
| `frontend/src/components/history.tsx` | 列表中的失败状态与归档说明 |

## 验证方式与边界

`cd frontend; npm.cmd test` 验证快照保留、多个片段、SSE 与历史结果一致、旧字段兼容、纯文本转义、零评分、失败报告边界以及既有协议行为。`npm.cmd run typecheck` 检查类型，`npm.cmd run build` 检查生产构建。

浏览器验收脚本为 `frontend/tests/browser-knowledge.js`，目标为本机 `3015` 测试端口，使用明确的隔离接口数据。Playwright CLI 打开该端口后，通过 `run-code --filename=frontend/tests/browser-knowledge.js` 执行。覆盖待补信息、多片段、时间线、纯文本、快照版本、窄屏、Esc 焦点恢复、历史打开及刷新。脚本不访问供应商，不生成真实诊断，不代表真实模型语义引用已验收。

真实端到端验收需要后端存储就绪、知识资料发布并启用工具，随后由诊断模型实际调用检索并生成终态。2026-10-15 本机服务历史接口返回 `STORAGE_NOT_READY`；更新网页并重启统一服务后，同源能力接口返回 `persistence=false`，未返回 `knowledge_search`。因此当前运行环境不能声明知识检索已经启用，也没有完成真实知识诊断及数据库回查验收。此对接没有变更后端代码、迁移、模型连接或存储配置。
