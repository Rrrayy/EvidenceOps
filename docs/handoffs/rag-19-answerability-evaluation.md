# RAG 19：可回答性与证据支持评测基线

## 目标

为 R0-2 建立固定回归输入，区分“检索到相关知识”和“当前问题能否据此回答”。本批没有增加线上 query 改写模型、相似度拒答阈值或新的诊断控制流。

评测案例代表需要覆盖的风险类型，不是对线上用户问题的预测。它们固定 query、当前现场事实、人工标注片段和报告审核标准，以便在检索/生成策略改变时比较行为。

## 案例类别

新增 `samples/knowledge/answerability_cases.json`，包含五例：

| 案例 | 预期 | 当前能评估什么 |
|---|---|---|
| Python 下一步排查 | 引用手册给解释器核验步骤 | 必需排查片段是否进入 Top-3 |
| Python 本次根因，缺运行时信息 | `insufficient_evidence`，要求补充解释器与 pip 结果 | 检索可命中相关手册，但报告是否克制需生成审核 |
| React 资料不适用 | 不拼凑手册，不伪造引用 | 记录无标注相关片段时检索仍返回候选的比例 |
| Java 版本/适用范围不匹配 | 不把堆内存资料当作虚拟线程结论 | 当前语料没有版本范围标签，属于压力输入而非已覆盖的适用性判定 |
| PostgreSQL 15/17 冲突 | 不推断 pgvector/HNSW 兼容性 | 当前语料没有该版本对照资料，属于待补知识的压力输入 |

每例包含场景类别、可回答性标签、预期报告策略、现场已知事实、相关/必需 Chunk ID 和人工审核标准。知识排障方法与本次运行观测分开描述。

## 检索统计

`tests/test_bm25_corpus.py` 对冻结的 37 个 Chunk 跑 BM25 Top-3，并按场景输出候选非空数和必需片段命中数。`knowledge_comparison` 支持同一案例格式，可对 cosine、keyword、BM25、keyword-RRF、BM25-RRF 产生逐题结果及按场景摘要。输出显式包含 `answerability_assessed=false`，防止把检索排序误读成报告语义结论。

本地确定性 BM25 观察结果：

- 两道 Python 题都命中必要的解释器排查片段。根因题虽然可回答性标签为 `needs_incident_evidence`，检索仍然命中手册，这是预期现象，不能把命中当成根因确认。
- React 无适用资料题返回 3 个候选。
- Java 21 适用范围题返回 3 个候选，其中出现 Java 堆内存资料。
- PostgreSQL 版本冲突题返回 3 个候选，其中有通用 PostgreSQL 资料。
- 三类无已标注适用片段的题都返回了候选，BM25 没有自动拒答能力。

这是检索压力观察，不证明候选都相关，也没有真实聊天模型报告质量结论。

分场景 Top-3 非空统计为：知识可回答 `1/1`、需要现场证据 `1/1`、无适用知识 `1/1`、适用范围未建模 `1/1`、版本冲突未建模 `1/1`。根因题的必需手册片段命中 `1/1`，但预期仍是证据不足；这直接验证“检索命中率”和“根因可回答性”不能合并成一个指标。

## Agent 拒答契约

新增确定性回归把“只有参考手册、没有本次运行时事实”的根因问题送入 Agent。Mock Provider 明确返回 `insufficient_evidence`，测试确认系统保存 `failed / EVIDENCE_INSUFFICIENT`、`report=null`、缺失信息和已召回知识 Evidence。此测试检查响应与持久化契约，不能证明真实模型会自主选择拒答。

人工或真实模型审核每条输出时，按案例 `review_criteria` 判断：

- 排查方法问题是否给出资料支持的核验步骤。
- 根因问题是否把环境错配保留为假设，并要求现场观测。
- 无适用资料时是否拒绝拼凑答案。
- 版本/适用范围未知时是否披露边界而非套用相似文档。
- 引用正文是否支持相邻的具体 claim。

引用 ID 有效、Evidence 正文快照一致、报告语义受正文支持是三项不同检查。

## 复现

本地 BM25-only 固定语料回归无需 Embedding 凭据：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pytest tests/test_bm25_corpus.py -q -s
```

五路检索对照需 PostgreSQL 和 Embedding 配置。使用新输出文件名，避免覆盖现有实验：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.application.knowledge_comparison --cases samples/knowledge/answerability_cases.json --top-k 3 --candidate-k 10 --output samples/knowledge/answerability_comparison_result.json
```

报告生成质量需通过真实聊天模型逐例运行并人工审核。当前案例 JSON 是评测输入和标准，不是自动语义 Judge。

## 验收边界

本批可以验收固定案例可加载、BM25 对照可重复、必需片段与无资料候选行为有逐题记录、证据不足终态契约正确。真实模型的拒答率、claim support、无依据断言率仍待人工审核；适用版本过滤也未实现。不得把这批结果描述成“RAG 已能自动判断可回答性”。

验证结果：`tests/test_bm25_corpus.py`、混合检索、知识 Agent、对照 CLI 和诊断评测共 **68 passed、4 skipped**，另有一条既有 Starlette/httpx 弃用警告。新增 BM25 Agent 流程在 SQLite 与 PostgreSQL 随机 schema 上均通过，**2 passed**；临时 schema 已清理。`git diff --check` 通过。
