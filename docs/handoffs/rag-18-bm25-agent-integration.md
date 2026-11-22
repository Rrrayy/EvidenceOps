# RAG 18：BM25 Agent 与 SSE 历史链路验收

## 本批目标

上一批确认了 PostgreSQL 上的 BM25 工具可以在没有 Embedding Provider 和向量集合时检索文本。本批把同一条路径接到 Agent HTTP 流程，验证工具结果在模型生成报告前绑定 Evidence，并在 SSE 终态与历史接口中保持一致。

本批不调整 BM25 参数，不切换默认检索模式，不接入 LangChain，也不把确定性模型替身描述为真实聊天模型。

## 执行链路

```text
发布只含 ChunkSet 的文档
        -> 根据服务端配置构造 BM25 知识工具
        -> Agent 发起 search_knowledge 工具调用
        -> BM25 从 PostgreSQL 或 SQLite 读取 Chunk 正文
        -> ToolEvidenceCollector 在下一轮模型请求前绑定 Evidence ID
        -> 确定性 Provider 使用模型可见正文和 Evidence ID 生成报告
        -> SSE 返回 run_completed 与报告
        -> GET /api/v1/agent/runs/{run_id} 回查 Evidence 和执行记录
```

Embedding 环境变量被清除，`configured_embedding_provider` 被替换为“调用即失败”。发布指针断言为 `(chunk_set_id, None)`，检索元数据中的 `embedding_set_id` 也必须为 `None`。因此测试不仅验证 BM25 排序结果，还会在 Provider 被错误创建时直接失败。

## 修改文件

- `tests/test_knowledge_agent.py` 增加 SQLite/PostgreSQL 参数化集成测试。PostgreSQL 分支在随机 schema 中创建表，退出时删除该 schema，不写入 `public`。
- `docs/handoffs/rag-18-bm25-agent-integration.md` 记录执行链路、断言、测试边界和当前结果。

## 主要断言

1. 知识文档可以在没有 EmbeddingSet 的情况下发布。
2. `configured_knowledge_tools` 在 `bm25` 模式下不会创建 Embedding Provider。
3. 模型收到的工具结果包含 BM25 片段正文、来源元数据和独立 Evidence ID。
4. 模型使用这些 ID 生成报告后，SSE 产生唯一 `run_completed` 终态。
5. 历史接口返回的 `content_snapshot`、Evidence ID、来源元数据与模型看到的内容一致。
6. Evidence 记录 `retrieval_method=bm25-v1` 且 `embedding_set_id=null`，报告引用的 ID 存在于返回 Evidence 中。

## 验收结果

本机没有 `EVIDENCEOPS_MODEL_BASE_URL`、`EVIDENCEOPS_MODEL_API_KEY`、`EVIDENCEOPS_MODEL_NAME`，也没有运行中的 Agent API 服务。项目本地虽有加密模型连接文件，但当前 Windows 用户上下文无法通过 DPAPI 解密，因此真实聊天供应商请求没有执行。本测试使用 `MockProvider` 固定工具调用和报告内容，验证 Agent、检索、Evidence、SSE、持久化与历史回查之间的应用契约，不代表真实模型会稳定选择知识工具，也不代表生成内容通过语义审核。

`tests/test_knowledge_agent.py` 全文件结果为 **36 passed、1 条既有 Starlette 弃用警告**。新增用例的 SQLite 和 PostgreSQL 分支都通过。PostgreSQL 分支需要测试进程设置 `POSTGRES_PASSWORD`，创建随机 schema、通过 SQLAlchemy schema 映射初始化表并在结束时级联删除；测试后查询确认没有残留 `bm25_agent_*` schema。临时 schema 清理失败会导致测试失败。

## 验证命令

在项目虚拟环境中运行：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_agent.py -q -rs
```

若没有 `POSTGRES_PASSWORD`，PostgreSQL 参数化分支会显示 skipped；SQLite 分支仍会执行。真实聊天模型验收还需要启动 Agent API，并通过项目受支持的模型连接方式配置凭据。不要把密钥写入测试报告或提交到仓库。

## 后续边界

确定性集成测试通过后，下一层才是用已配置的真实聊天模型发起一次受控诊断，检查模型是否选择 `search_knowledge`、回答是否受到可见手册正文支持，以及 SSE 和历史响应是否一致。真实模型行为具有非确定性，不能替代本测试中的稳定回归断言。
