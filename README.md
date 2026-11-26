<div align="center">
<img src="https://capsule-render.vercel.app/api?type=soft&height=280&color=0:0b1f3a,100:14355f&section=header&text=EvidenceOps&fontSize=72&fontColor=e8f1fb&desc=Evidence-driven%20workbench%20for%20software%20incident%20diagnosis&descSize=18&descAlignY=62" width="100%" alt="EvidenceOps"/>
</div>

<p align="center">
  <a href="README.en.md"><img alt="English" src="https://img.shields.io/badge/切换语言-English-14355f?style=for-the-badge"></a>
</p>

<p align="center">
  <a href="#快速启动">快速启动</a> · <a href="#核心能力">核心能力</a> · <a href="#评测">评测</a> · <a href="#系统架构">系统架构</a> · <a href="#测试">测试</a>
</p>

<p align="center">
  <img alt="python" src="https://img.shields.io/badge/python-3.14-3776AB">
  <img alt="node" src="https://img.shields.io/badge/node.js-%E2%89%A520.9-339933">
  <img alt="cpp" src="https://img.shields.io/badge/C%2B%2B-20-00599C">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-blue">
</p>

> **当 AI 告诉你"根因是 order-service 的配置变更"，你拿什么向团队证明它不是猜的？**

**每一条诊断结论都绑定同一次 Run 内采集的证据**——来源、观测时间、位置、版本、内容哈希与归档快照——事后可对质，即使原始日志已经轮转。

<p align="center"><img src="docs/assets/console-evidence-citation.png" alt="诊断报告、E01–E03 证据引用与执行轨迹同屏" width="880"/></p>

*报告、证据引用与执行轨迹同屏。截图使用 Mock 演示数据，结论已标注为演示输出。*

**这是什么。** 面向软件运行故障的本机诊断工作台。Agent 通过受限的只读工具查询日志、指标、配置和排障资料，将一次运行中的观测证据与诊断建议关联起来。网页控制台提供运行跟踪、证据检查、模型连接管理和历史回查。

**演示模式：**仓库提供确定性的 Mock 模型和 `order-service` 样例数据。Mock 返回固定演示结论，不会理解用户输入；报告会明确标记为演示。网页也可以配置真实的 OpenAI-compatible 诊断模型。

**它不做什么。**

- 它不是多租户服务：没有远程身份认证、多用户授权与分布式协调——一台本机、一个 API worker。
- 诊断输入中的粘贴或导入文本只作为问题描述，不会自动上传为日志证据。日志文件由部署者在服务端登记，经 C++20 解析管线的受控查询转成证据；这不是任意路径访问或通用语言运行时解析。
- 引用校验只证明证据的身份与归属，不证明来源在语义上支持结论；对质仍由你完成。
- Inno Setup 配置尚未构建并验收为可发布安装包；请以源码方式运行。

## 核心能力

<details>
<summary><strong>15 个能力组</strong>——受控工具执行、证据化报告、离线检索评测（点击展开）</summary>

| 能力 | 行为 |
| --- | --- |
| 诊断编排 | 独立于供应商的 Agent Loop、OpenAI-compatible 适配器、确定性 Mock |
| 受控工具 | 白名单注册、参数校验、有界执行、工具调用关联与协作取消 |
| 日志解析 | C++20 CLI 解析受支持格式，Python Adapter 校验版本化 JSON 并生成可追溯日志 Evidence |
| 证据报告 | 来源、观测时间、位置、版本、内容哈希、运行内引用校验与历史快照 |
| 网页控制台 | 诊断工作台、可检索历史、证据抽屉、执行时间线与离线评测查看 |
| 模型连接 | 加密凭据、模型目录、显式能力验证、默认配置与本次诊断选择 |
| 历史归档 | 安装版默认 SQLite，可切换至受管理的 PostgreSQL |
| 安装与存储 | 首次设置、连接检查、存储切换、逻辑备份导入导出与恢复 |
| 流式与重连 | SSE 生命周期事件，按游标补发，不重新执行诊断 |
| 上下文治理 | 每轮输入估算、输出与安全余量预留、Run 累计预算、供应商用量记录与上下文审计归档 |
| 执行控制 | 共享时间预算、单次超时与协作取消 |
| 启动收尾 | 单实例锁保护；遗留 Run 原子失败并追加终止事件 |
| 诊断评测 | 20 案例离线题库、自动规则及可恢复的 CLI 人工审核 |
| 知识检索 | 文档版本、ChunkSet、EmbeddingSet、向量持久化、精确 cosine、关键词、BM25 与 RRF 对照 |
| 检索评测 | 片段级 Precision、Recall、MRR 与必需片段命中对照 |

</details>

## 快速启动

需要 Python 3.14、Node.js 20.9 或更高版本以及 PowerShell 7。以下命令均在仓库根目录执行。只有可选的 PostgreSQL 开发服务需要 Docker Compose；安装版默认使用 SQLite。

### 启动完整应用（推荐）

**使用网页控制台请通过此入口同时启动前后端。** 首次下载后，先在仓库根目录安装依赖并构建前端：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
pwsh -File scripts/start_installed.ps1
```

打开 [EvidenceOps](http://127.0.0.1:3013)。启动脚本运行 8014 安装版 API 与 3013 网页，统一数据目录和服务端管理令牌。全新安装默认使用 SQLite 与 Mock；首次设置检查存储、模型配置，并明确当前数据源为样例。

依赖与构建准备好后，日常启动只需在仓库根目录执行：

```powershell
pwsh -File scripts/start_installed.ps1
```

保持此终端运行。按 `Ctrl+C` 停止前后端；关闭终端后服务不会继续提供网页，也不会自动在开机时启动。再次运行同一命令即可启动，使用同一数据目录时保留已有历史和配置。更新前端源码后，停止服务并重新执行 `npm.cmd ci`、`npm.cmd run build`（在 `frontend` 目录），再启动脚本。

| 服务 | 默认地址 | 用途 |
| --- | --- | --- |
| 网页控制台 | `http://127.0.0.1:3013` | 用户访问入口 |
| 安装版 API | `http://127.0.0.1:8014` | 网页后台及存储管理 |

启动脚本设置网页代理与数据目录，无需额外启动 `npm run start` 或手动修改前端代理地址。下方的单独开发 API 命令仅启动后端，不会启动网页。

### Windows 安装包状态

仓库中包含 `installer/EvidenceOps.iss` Inno Setup 配置，但尚未编译并验证为可交付的客户安装程序。现阶段请按上方源码安装步骤部署。客户安装、数据目录、备份和运行边界见[本机安装与数据存储](CUSTOMER_INSTALLATION.md)。

| 启动问题 | 处理方式 |
| --- | --- |
| 找不到 `pwsh` | 安装 PowerShell 7，并重新打开终端 |
| 找不到 `node` 或 `npm.cmd` | 安装符合要求的 Node.js，并重新打开终端 |
| 提示依赖或前端构建未准备好 | 完成上面的首次安装命令，确认 `npm.cmd run build` 成功 |
| 端口被占用 | 停止原实例，或指定不同的 `-ApiPort` 和 `-WebPort`，访问新的网页端口 |
| 浏览器显示拒绝连接 | 确认启动终端仍在运行；若脚本退出，检查该终端错误信息后重新启动 |

可用 `-DataDirectory D:/EvidenceOpsData -ApiPort 8014 -WebPort 3013` 调整启动参数。当前采用源码安装，没有打包安装程序。迁移与备份细节见[本机安装与数据存储](CUSTOMER_INSTALLATION.md)。

### 单独启动开发 API

开发入口保留显式 memory/PostgreSQL 模式，不提供安装存储管理。`requirements.txt` 固定后端运行依赖，`requirements-dev.txt` 包含测试依赖。

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
$env:EVIDENCEOPS_PROVIDER='mock'
$env:EVIDENCEOPS_PERSISTENCE='memory'
.\.venv\Scripts\python.exe -m uvicorn evidenceops.api.agent_app:app --host 127.0.0.1 --port 8000
```

打开 [API 文档](http://127.0.0.1:8000/docs)。此模式无需数据库或模型凭据；持久化历史与重放不可用。

前端单独开发时，在 `frontend` 执行 `npm ci`，在前端终端将 `EVIDENCEOPS_API_URL` 指向该 API，再执行 `npm run dev`，默认网页端口为 3000。开发存储管理页面需连接安装版 API。代理目标属于服务端配置，不允许浏览器指定任意目标地址。

### 为开发 API 启用 PostgreSQL

切换配置前停止 API。在本地未跟踪的 `.env` 设置 `POSTGRES_PASSWORD=<你的本地密码>`。Compose 读取该文件，Python 读取环境变量。

```powershell
$env:POSTGRES_PASSWORD=((Get-Content .env | Where-Object { $_ -match '^POSTGRES_PASSWORD=' } | Select-Object -First 1) -replace '^POSTGRES_PASSWORD=','')
docker compose up -d postgres
docker compose ps
$env:EVIDENCEOPS_PERSISTENCE='postgres'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn evidenceops.api.agent_app:app --host 127.0.0.1 --port 8000
```

等待 PostgreSQL healthy 后迁移。宿主机连接 `127.0.0.1:5433`，容器内监听 `5432`。命名卷在容器替换后保留数据库文件，删除卷会删除数据。初始化后修改密码变量不会更改已有数据库角色密码。开发 API 需显式迁移；安装版自动管理 SQLite 迁移，并在存储页面提供需确认的 PostgreSQL 初始化和升级。

### 配置真实模型

网页中通过**设置 → 模型连接**保存并验证用户连接，再在诊断输入区附近选择。也可在 API 终端配置以下变量并重启，提供只读系统连接：

```powershell
$env:EVIDENCEOPS_PROVIDER='openai-compatible'
$env:EVIDENCEOPS_MODEL_BASE_URL='https://your-provider.example/compatible-mode/v1'
$env:EVIDENCEOPS_MODEL_NAME='your-tool-capable-model'
$model_secret=Read-Host '模型 API Key' -AsSecureString
$env:EVIDENCEOPS_MODEL_API_KEY=[System.Net.NetworkCredential]::new('', $model_secret).Password
Remove-Variable model_secret
$env:EVIDENCEOPS_MODEL_TIMEOUT_SECONDS='120'
$env:EVIDENCEOPS_RUN_TIMEOUT_SECONDS='180'
```

替换为供应商实际地址和模型。适配器使用 Chat Completions 工具调用与 JSON-object 输出；仅声明接口兼容不代表完整支持协议。真实请求产生供应商费用。

## 系统架构

```mermaid
flowchart TD
    Browser["网页控制台：Next.js / React"] --> Proxy["同源 API 代理 / AI SDK SSE 适配"]
    Proxy --> Install["安装与存储管理"]
    Install --> API["FastAPI 诊断 API"]
    Client["HTTP / SSE 客户端"] --> API
    API --> Service["Diagnosis Service"]
    Service --> Loop["Agent Loop"]
    Loop --> Context["Context Assembler / Token Ledger"]
    Context --> Gateway["LLM Gateway"]
    Gateway --> Provider["Mock / OpenAI-compatible 模型"]
    Loop --> Runtime["Tool Runtime"]
    Runtime --> Samples["样例日志 / 指标 / 配置 Connector"]
    Runtime --> Parsed["白名单日志工具"]
    Parsed --> Adapter["Python Adapter：资源限制与 JSON 校验"]
    Adapter --> CLI["C++20 日志解析 CLI"]
    CLI --> Files["服务端登记的本机日志文件"]
    Runtime --> Knowledge["知识检索工具"]
    Knowledge --> Corpus["关系数据库：已发布知识与向量"]
    Samples --> Evidence["Evidence Collector"]
    Evidence --> Loop
    Loop --> Report["结构化草稿 / 引用校验 / 报告"]
    Report --> Service
    Service --> Store["SQLite / PostgreSQL：Run、证据、报告、执行记录、事件、模型快照"]
    API --> History["历史查询与事件重放"]
    History --> Store
    Proxy --> Connections["模型连接管理 / 加密凭据"]
    Connections --> Provider
    Eval["离线评测 / CLI 审核"] --> Service
```

模型提出工具调用，Tool Runtime 只执行服务端已注册且通过参数校验的能力。日志文件经过 C++ CLI 解析及 Python 边界校验后才成为 Evidence；知识片段作为排障参考单独标识。应用层负责 Run 生命周期、上下文预算、取消和报告构建，基础设施层提供数据库及模型适配器。

### 日志证据链路

`query_parsed_logs` 只接受服务端清单中登记的 `source_id`，不会让模型传入文件路径。当前 C++20 解析器覆盖项目 RPC 样本中出现的 glog、ZooKeeper、muduo 和普通文本规则；不匹配或损坏的行会保留为 `unknown` 并附带警告。只有带 UTC 标记的 muduo 时间会生成确定时间，其他未包含时区的格式不会猜测时区。格式识别范围有限，不代表已支持任意语言、框架或日志平台。

Python Adapter 对输入大小、进程时间、stdout/stderr、事件数量和结果 JSON 做边界检查，并验证来源、行范围、统计字段和事件格式。每次查询重新读取登记文件；单次返回最多 20 条事件，选择结果有字符预算，过大事件会跳过而不会截断。Adapter 为完整输入快照计算 SHA-256，日志 Evidence 保存该哈希、版本化解析快照、行范围、解析状态、选择游标和导入观测时间；单独运行 C++ CLI 时哈希字段为未计算。续读发生在后续调用；调用方应比较输入哈希，避免把文件变化前后的结果误认为同一快照。

启用日志工具需要同时设置 `EVIDENCEOPS_LOG_SOURCES_FILE` 和 `EVIDENCEOPS_LOG_PARSER_BINARY`。清单为服务端维护的 JSON 文件，例如：

```json
[
  {"source_id":"rpc-server","path":"C:/logs/server.log","role":"server"},
  {"source_id":"rpc-client","path":"C:/logs/client.log","role":"client"}
]
```

清单路径由部署者控制，来源角色为 `server`、`client` 或 `unknown`。导入到诊断输入框的文本不会注册来源；当前没有面向客户的日志上传、路径配置界面、日志保留平台或通用解析器市场。

### 上下文窗口与 Token 预算

每次模型请求前，Agent Loop 都会对当前完整消息历史、工具定义和响应格式进行估算，并为输出上限和安全余量预留空间。默认配置为上下文窗口 `32768`、单次输出 `2048`、安全余量 `256`、单次 Run 累计预算 `16384` Token。模型连接可以按模型单独保存这些限制；每次运行会保存配置快照。

当前 `heuristic-json-v1` 是按序列化文本长度估算的启发式方法，不是供应商 tokenizer，也不构成精确容量保证。供应商返回用量时，系统记录输入、输出和总 Token；缺失或无效时会保留对应计量状态。超出单请求上下文或 Run 累计预算时，请求在发往模型前失败，不会静默截断或丢弃历史。**自动摘要、按证据优先级裁剪、分块压缩和供应商 tokenizer 适配尚未实现。**前端时间线展示每轮估算值、输出预留值及可用的供应商用量；SSE 传输执行事件，不流式输出模型 Token。

启用上下文治理与持久化后，已完成组装的模型请求会记录轮次、请求 ID、请求载荷哈希、实际估算器标识、输入 Token 估算、输出预留、可见证据 ID、去重映射和省略记录。审计记录随成功、失败或取消 Run 的终态档案在同一事务中提交；同一 Run 和模型请求 ID 的重复写入不会追加重复记录。审计表不保存完整消息正文，载荷哈希也不能用于还原消息；知识证据的正文快照单独随 Evidence 保存。当前没有面向前端的上下文审计查询接口。

可见证据 ID 的审计目前覆盖已绑定证据投影的知识检索和解析日志结果。普通 `query_service_logs`、`query_service_metrics`、`query_service_config` 结果仍进入模型工具历史，但尚未绑定对应审计投影，因此其可见 ID 记录可能为空；空记录不能解释为模型未收到工具数据。终态事务提交前进程崩溃，内存中收集的上下文审计可能丢失。

### 知识组件

知识层将参考资料与故障观测分开处理。逻辑文档拥有按内容生成身份的版本；同一版本可以有多套绑定切分算法和配置的片段集合。片段保留原文范围、标题路径和内容哈希。本地加载必须明确指定知识用途，只读取配置目录和字节限制内的 UTF-8 Markdown/TXT。

SQLAlchemy 仓储保存文档、不可变版本、切分集合、编码配置和向量。每份文档的发布指针必须选择一个 ChunkSet，并可选关联完整且 ready 的 EmbeddingSet。BM25 和关键词检索直接读取已发布文本，不需要向量或 Embedding 凭据；cosine 与混合检索需要匹配该 ChunkSet 的向量集合。PostgreSQL 将 Embedding 保存为 pgvector 原生向量列，数据库执行 cosine 查询；按向量维度与编码配置指纹隔离的 HNSW 索引提供近似检索。旧 JSON 向量在迁移后保留作精确对照与回滚数据。发布在短事务中校验整个指针，Embedding 构建失败不会切换旧发布。摄取、构建、发布通过内部 CLI 操作，没有知识管理 HTTP 接口或工作台操作入口。

独立的 OpenAI 兼容 Embedding 适配器支持真实编码。显式启用 `search_knowledge` 后，Agent 可检索服务端配置的至多 16 份文档白名单；BM25/关键词直接查发布文本，cosine/混合模式校验编码配置并只编码一次查询，各路共享候选预算并统一排序。每个片段在下一轮模型请求前绑定独立 Evidence ID。本次可见正文、哈希、来源版本、片段身份、分数和检索配置身份一起归档，并进入诊断及历史响应，失败 Run 同样保留。零命中不生成 Evidence；检索故障沿用终止诊断的工具失败策略。默认 Mock 场景不会自动调用知识工具。

配置项：`EVIDENCEOPS_KNOWLEDGE_ENABLED=true`、`EVIDENCEOPS_KNOWLEDGE_DOCUMENT_IDS`（逗号分隔，兼容旧单数配置 `EVIDENCEOPS_KNOWLEDGE_DOCUMENT_ID`）。仅 cosine/混合检索需要 `EMBEDDING_PROVIDER`、`EMBEDDING_ENDPOINT`（完整 HTTPS `/embeddings` 地址）、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSIONS`、`EMBEDDING_API_KEY`（或 `DASHSCOPE_API_KEY`）；BM25/关键词检索无需 Embedding 凭据。可选模型修订和文档/查询前缀必须与已发布编码配置一致。启用前执行 `alembic upgrade head`；诊断模型凭据独立配置。`scripts/verify_knowledge_agent.py` 使用真实 Embedding、PostgreSQL 和确定性生成替身验证引用及失败保留。

练习语料清单位于 `samples/knowledge/manifest.json`，覆盖 RPC 超时、Python 导入、PostgreSQL 连接、SQLAlchemy 连接池、Java 堆内存、Go 数据竞争和 Rust panic。资料为引用官方文档的原创摘要，不能视为现场观测或完整的多语言支持承诺。向量/混合检索需要 Embedding 配置；只准备词法检索时，可在内部 CLI 使用 `--lexical-only` 发布文本片段，不调用 Embedding 服务。

```powershell
python -m evidenceops.application.knowledge_corpus_cli prepare samples/knowledge/manifest.json --publish
python -m evidenceops.application.knowledge_corpus_cli evaluate samples/knowledge/manifest.json
```

发布以单份文档为原子单位，不是整库原子切换；重复构建未变化且已发布的资料会复用已有集合。检索支持 PostgreSQL 精确 cosine、PostgreSQL HNSW cosine、旧关键词、BM25、关键词-RRF 和 BM25-RRF。`EVIDENCEOPS_KNOWLEDGE_VECTOR_SEARCH=auto` 在 PostgreSQL 上使用 HNSW，在 SQLite 上使用精确路径；可显式设为 `exact` 做同库基准。HNSW 当前只为不超过 2000 维的配置建索引，且每个索引按维度和配置指纹隔离；超出范围会要求显式切换到精确模式，不降维或混搜。`EVIDENCEOPS_KNOWLEDGE_RETRIEVAL=bm25` 或 `hybrid_bm25` 可选择词法实验模式，默认仍为 cosine；BM25 使用固定英文词/中文单字分词及 `k1=1.2,b=0.75`，旧 `hybrid` 模式继续保留。BM25 只依赖 ChunkSet 文本；混合检索要求发布指针同时关联该 ChunkSet 的 ready EmbeddingSet。BM25 与 RRF 分数不是余弦相似度，分路排名和参数随检索元数据归档。

#### 当前检索对照结论

内部检索对照快照使用 7 份手册、37 个片段；开发题 17 道（15 道正例），另有 8 道内部留出题（7 道正例）。指标只衡量标注相关片段的 Top-3 检索，不衡量真实报告正确率。留出题由项目开发者编写，不是第三方盲测；留出题集和结果报告当前不都在 Git 跟踪中，因此这些数字是项目进度证据，不是克隆仓库即可完整复现的公开基准。

| 题集 | 方法 | Recall@3 | 必需片段命中 |
| --- | --- | ---: | ---: |
| 开发 | cosine | 72.22% | 13/15 |
| 开发 | BM25 | 71.11% | 14/15 |
| 开发 | BM25-RRF | 74.44% | 14/15 |
| 留出 | cosine | 85.71% | 7/7 |
| 留出 | BM25 | 78.57% | 6/7 |
| 留出 | BM25-RRF | 78.57% | 6/7 |

结论是保留 cosine 默认，将 BM25 与 RRF 作为可显式选择的对照方法；小样本下没有一种方案稳定全面胜出。三道无适用资料题在五种方法下均返回候选，因此非空结果不代表可回答，也不具备自动无答案识别能力。检索引用和报告语义支持仍须分层验收。

资料不足以支持诊断时，模型可返回独立的 `insufficient_evidence` 结果。系统将其保存为 `failed / EVIDENCE_INSUFFICIENT`，`report=null`，保留已有观测，并通过 `error_detail` 返回不足原因及 `missing_information`。诊断响应、终止 SSE 和历史查询均可读取说明。格式错误仍为 `MODEL_PROTOCOL_ERROR`；正常报告仍须引用有效证据，引用存在不等于语义支持成立。

每次检索最多五个片段、总正文最多 16,000 字符。默认不设相似度阈值，无关问题仍可能返回 Top-K；空结果处理不等于自动识别无答案。HNSW 是近似索引，已保留 pgvector 精确查询与旧 JSON 精确 cosine 作对照；候选数和过滤结果仍受查询预算限制。资料属于不可信数据，不能证明本次故障因果；引用存在性检查和提示约束不保证语义正确，也不能完全防止提示注入。重排、父子片段检索及 MMR 尚未实现。取消会停止等待并拒绝晚到结果，已经运行的同步 Embedding HTTP 请求不会被强制终止。

| 目录 | 职责 |
| --- | --- |
| `src/evidenceops/domain/` | Run 生命周期、Evidence 与报告约束 |
| `src/evidenceops/application/` | 编排、接口契约、收集、历史查询与启动收尾 |
| `src/evidenceops/infrastructure/` | SQLAlchemy 仓储和模型供应商 |
| `src/evidenceops/connectors/` | 本地只读数据源 |
| `src/evidenceops/api/` | HTTP 接口与 SSE 传输 |
| `src/evidenceops/evaluation/` | 离线检查与审核 CLI |
| `frontend/src/components/` | 诊断、历史、评测、模型连接与存储页面 |
| `frontend/src/lib/`、`frontend/src/app/api/` | 类型契约、Run 状态、SSE 解析与受控同源代理 |
| `scripts/` | 本机服务启动入口 |
| `alembic/`、`tests/`、`samples/` | 迁移、回归测试与可复现样本 |

## 网页控制台

前端采用 Next.js 16 App Router、React 19、TypeScript、AI SDK 6、assistant-ui、Radix Dialog 与 Tailwind CSS 4。五个页面使用石墨色侧栏、中性工作区、紧凑表单，以及对应真实结果的状态色。

| 页面 | 职责 |
| --- | --- |
| 诊断工作台 | 文本输入与本地文本导入、本次模型选择、实时执行时间线、取消、报告与可点击证据引用 |
| 运行历史 | 服务端搜索、状态筛选、分页、Run ID 查询及地址刷新回查 |
| 评测结果 | 本地只读导入 schema_version=1 的 JSON，校验统计并查看规则和人工审核状态 |
| 模型连接 | 添加、编辑、删除、替换凭据、获取目录、显式验证及独立全局默认 |
| 数据与存储 | 首次设置、实际存储状态、数据库检查、维护进度、备份与恢复 |

模型供应商请求由受控后端执行。凭据只在创建或替换时提交，读取接口不返回 API Key；密钥不进入浏览器持久存储、URL 或日志。接口目录、推荐项和手填模型均不代表账号有权限或满足 Agent 要求。验证分别检查认证、模型调用、工具结果关联及结构化报告，可能产生少量供应商费用。

工作台临时选择不改变全局默认。每个 Run 保存连接名称、供应商、请求/实际模型及配置版本；后续修改或删除连接不改写历史。旧 Run 缺少模型信息时显示“未记录”。Embedding 与 Rerank 按用途独立管理，切换诊断模型不会重配这些能力或重建索引。

`POST /api/diagnosis` 将 AI SDK 消息适配为一次后端诊断。取得 Run ID 后，断线按有界退避恢复 GET 观察，不重复创建。事件按 Run ID 与序号去重，拒绝缺口和跨 Run 数据。传输失败与业务失败分别表达；关闭观察连接不取消后台诊断，取消需要显式请求。

证据视图展示已归档的摘要、位置、时间、版本与哈希，不提供原始日志全文。离线评测文件只在浏览器读取，不启动在线评测。接口细节见[模型连接接口契约](frontend/MODEL_CONNECTIONS_CONTRACT.md)。

故障输入由页面、代理及后端进行结构校验：拒绝空白、纯标点、纯符号及超过 100000 字符的描述，允许短错误码和多语言日志。字符校验不能判断语义是否充分。Mock 使用固定工具调用与报告，不理解输入；报告按运行快照显示“Mock 演示报告”和“样例置信度”。目前 Mock 仍可从工作台发起，尚未分离独立演示入口。

### 前端开发与文件职责

| 目录 | 职责 |
| --- | --- |
| `frontend/src/components/` | 工作台、历史、评测、模型连接和存储页面 |
| `frontend/src/lib/` | 类型契约、事件解析、运行状态、证据编号和接口请求 |
| `frontend/src/app/api/diagnosis/` | AI SDK 消息与后端 SSE 的适配 |
| `frontend/src/app/api/backend/` | 固定目标、路由白名单和维护令牌转发 |
| `frontend/src/app/globals.css` | 样式、状态、焦点和响应式布局 |
| `frontend/tests/` | 单元测试、隔离后端与 Playwright CLI 场景 |

单独开发前端时，先按上文启动 FastAPI，再在另一个终端运行：

```powershell
cd frontend
npm.cmd ci
$env:EVIDENCEOPS_API_URL='http://127.0.0.1:8000'
npm.cmd run dev
```

开发网页默认端口为 3000；`npm.cmd run start -- --port 3013` 可指定生产端口。单独启动安装版前后端时，两端必须使用同一 `EVIDENCEOPS_DATA_DIR`，Next.js 服务端从中读取管理令牌。完整应用优先使用根目录启动脚本，避免配置不一致。

## 数据与存储

安装版将程序文件与持久数据分离。Windows 默认目录为 `%LOCALAPPDATA%/EvidenceOps`，其他平台使用 `$XDG_DATA_HOME/evidenceops` 或 `~/.local/share/evidenceops`。目录在实际运行主机上解析，可通过 `EVIDENCEOPS_DATA_DIR` 覆盖。

Run、报告、证据摘要、执行记录、事件和模型快照保存到所选诊断数据库；模型连接使用独立加密配置库。SQLite 无需外部数据库服务。PostgreSQL 使用管理员准备的专用数据库和账号，程序不安装数据库服务器或创建数据库角色。

存储维护等待已有诊断和模型验证结束，同时拒绝新诊断。切换前备份，向空目标导入并校验后发布新配置。数据库故障时管理页面仍可访问，诊断暂停，不自动降级到内存模式。

安装入口从迁移链读取当前结构版本，拒绝未知或多头版本；知识能力按实际工具注册及存储就绪状态声明。逻辑备份保存知识版本、片段、编码集合、向量、发布指针和Run正文快照，按原版本验证后转换旧档案，不伪造缺失正文。

逻辑备份支持创建、下载、导入和恢复，上限 100 MB。恢复需明确确认，并保留 Run 身份与引用关系；SQLite 使用新文件，PostgreSQL 要求目标为空。默认不包含 API Key；携带可迁移凭据需至少 12 字符的独立口令，由目标账号重新保护，恢复后的模型连接需要验证。仅复制 Windows DPAPI 密钥文件不能保证另一用户可以解密。

## 配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `EVIDENCEOPS_PROVIDER` | `mock` | `mock` 或 `openai-compatible` |
| `EVIDENCEOPS_PERSISTENCE` | 开发入口 `memory`；全新安装 SQLite | 开发入口 `memory`/`postgres`；安装版管理所选存储 |
| `EVIDENCEOPS_API_URL` | `http://127.0.0.1:8000` | Next.js 服务端代理目标，启动脚本设置 API 端口 |
| `EVIDENCEOPS_DATA_DIR` | 平台数据目录 | 安装版数据与管理令牌目录 |
| `EVIDENCEOPS_ADMIN_TOKEN_FILE` | `<数据目录>/admin.token` | 可选的 Next.js 管理令牌文件覆盖 |
| `EVIDENCEOPS_CONNECTIONS_DIR` | 安装版 `<数据目录>/model-connections`；开发入口 `output/model-connections` | 加密模型连接库 |
| `EVIDENCEOPS_CONNECTIONS_KEY` | 本机生成并保护 | 可选的外部 Fernet 密钥 |
| `EVIDENCEOPS_MODEL_ALLOWED_HOSTS` | `maas.qianwenaiapi.com,dashscope.aliyuncs.com` | 供应商主机白名单，包含自定义服务 |
| `EVIDENCEOPS_MODEL_ALLOW_HTTP` | 禁用 | 管理员显式允许 HTTP 模型接口 |
| `EVIDENCEOPS_MODEL_BASE_URL` | — | 模型基础地址 |
| `EVIDENCEOPS_MODEL_API_KEY` | — | 模型凭据 |
| `EVIDENCEOPS_MODEL_NAME` | — | 模型名称 |
| `EVIDENCEOPS_MODEL_TIMEOUT_SECONDS` | `60` | 真实模型单次超时 |
| `EVIDENCEOPS_RUN_TIMEOUT_SECONDS` | `180` | API 诊断预算 |
| `EVIDENCEOPS_CONTEXT_WINDOW_TOKENS` | `32768` | 系统连接使用的上下文窗口预算；用户模型连接可单独配置 |
| `EVIDENCEOPS_MAX_OUTPUT_TOKENS` | `2048` | 单次模型调用输出预留 |
| `EVIDENCEOPS_CONTEXT_SAFETY_MARGIN_TOKENS` | `256` | 输入估算与输出预留之外的安全余量 |
| `EVIDENCEOPS_MAX_RUN_TOKENS` | `16384` | 单次诊断的累计 Token 预算 |
| `EVIDENCEOPS_TOKEN_ESTIMATOR_ID` | `heuristic-json-v1` | Token 估算方法标识 |
| `EVIDENCEOPS_CONTEXT_LIMITS_SOURCE` | `local_conservative` | 窗口限制的来源标识，不代表供应商已验证 |
| `EVIDENCEOPS_LOG_SOURCES_FILE` | 未设置 | 服务端登记日志来源清单；设置后还需配置解析器程序 |
| `EVIDENCEOPS_LOG_PARSER_BINARY` | 未设置 | C++20 `log_evidence_cli` 可执行文件路径 |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `127.0.0.1` / `5433` | 宿主机数据库地址 |
| `POSTGRES_DB` / `POSTGRES_USER` | `evidenceops` / `evidenceops` | 数据库及角色 |
| `POSTGRES_PASSWORD` | — | PostgreSQL 模式必填 |

修改环境变量后重启。直接使用组装器或离线 Eval 不自动启用 API 的预算。

## HTTP API

| 方法 | 接口 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/agent/diagnosis` | 创建诊断，返回结果 |
| POST | `/api/v1/agent/diagnosis/stream` | 创建诊断，推送过程 |
| GET | `/api/v1/agent/runs/{run_id}` | 查询持久化状态与档案 |
| GET | `/api/v1/agent/runs/{run_id}/events` | 分页读取有序事件 |
| GET | `/api/v1/agent/runs/{run_id}/events/stream` | 补发并观察已有 Run |
| POST | `/api/v1/agent/runs/{run_id}/cancel` | 请求取消 |
| GET | `/api/v1/agent/capabilities` | 查询实际服务能力 |
| GET | `/api/v1/agent/runs` | 搜索、筛选和分页查询归档 Run |
| GET | `/api/v1/agent/model-services` | 查询支持的服务预设 |
| GET / POST | `/api/v1/agent/model-connections` | 查询或创建模型连接 |
| GET / PATCH / DELETE | `/api/v1/agent/model-connections/{id}` | 读取、编辑或删除连接 |
| PUT | `/api/v1/agent/model-connections/default` | 设置全局默认连接和模型 |
| POST | `/api/v1/agent/model-connections/{id}/catalog` | 获取模型目录 |
| POST | `/api/v1/agent/model-connections/{id}/validation` | 验证连接和模型能力 |
| GET | `/api/v1/agent/setup/status`、`/api/v1/agent/storage/status` | 安装设置与存储状态 |
| POST | `/api/v1/agent/storage/check` | 检查目标数据库连接 |
| POST / GET | `/api/v1/agent/storage/operations`、`/api/v1/agent/storage/operations/{id}` | 发起维护、读取进度 |
| GET / POST | `/api/v1/agent/storage/backups/{id}`、`/api/v1/agent/storage/backups/import` | 下载、导入逻辑备份 |

在另一个终端发送样本：

```powershell
curl.exe -N -X POST "http://127.0.0.1:8000/api/v1/agent/diagnosis/stream" -H "Content-Type: application/json" --data-binary "@samples/requests/sse-diagnosis.json"
```

诊断请求接收 `description`，可选 `connection_id`、`model_id` 和 `expected_version`。结果包含 ID、状态、时间戳、错误码、Evidence、报告、执行记录与可空的 `model_config`。同步诊断失败目前返回 HTTP 503；历史查询可以返回 HTTP 200 和 `status=failed`。HTTP 请求成功与诊断成功是两个维度。设置与存储接口要求安装版入口，维护写入使用服务端管理令牌。

SSE 发布 Run、模型和工具生命周期事件、可选取消请求，以及 `run_completed`、`run_failed` 或 `run_cancelled` 终止事件。推送的是执行过程，不是模型逐 Token 输出。

```powershell
$run_id=(Read-Host 'Run ID').Trim()
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/$run_id"
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/events?after=0&limit=100"
curl.exe -N "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/events/stream?after=2"
curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/cancel"
```

重放从游标之后开始，也可传 `Last-Event-ID: <run_id>:2`；两种游标同时提供必须一致。分页字段为 `events`、`next_sequence`、`max_sequence`、`has_more` 和 `status`，分页大小为 1～1000。GET 不创建诊断。客户端保存完整事件 ID 并去重；浏览器 EventSource 收到终止事件后应关闭。

取消 HTTP 202 表示接纳请求，不代表终态已提交。重复请求幂等，终态认领冲突返回 409。取消后的 Run 为 `status=cancelled`、`error_code=null`，报告为空。

## 可靠性与运行边界

- **持久化：** 业务事件提交后发送，最终 Run、业务档案和终止事件原子提交。传输失败不撤销提交；仅传输故障的 `stream_failed` 不带持久化 SSE ID。
- **重放：** 历史与新事件共用数据库游标。短 Session 在发送/等待前关闭，0.5 秒轮询，15 秒心跳。
- **容量：** 每进程 4 个 POST 流式诊断、16 个 GET 观察连接，分别限流；这不是同步 POST 的全局并发上限。
- **执行控制：** 协作检查拒绝迟到结果。提交、清理和非协作线程可能超过预算。本地取消模型不保证上游停止生成或计费。
- **启动收尾：** PostgreSQL 使用会话锁，安装版 SQLite 使用本机文件锁。遗留 `pending/running` 原子改为 `failed / RUN_INTERRUPTED` 并追加终止事件；重复启动幂等，不续跑 Agent。
- **崩溃边界：** 已提交档案保留。完整 Evidence、执行记录和上下文审计主要在收尾归档，因此可能事件已保存而对应业务档案与审计记录仍缺失。
- **部署范围：** 本机、单租户、单 worker，启用 lifespan。远程登录、多用户权限、分布式协调、自动保留/备份和客户数据源配置未实现。启动脚本监督子进程，停止脚本会终止这些进程；长期服务安装需另行配置进程管理与关停策略。

历史/重放要求持久存储：安装版 SQLite 或 PostgreSQL；开发入口内存模式不提供历史。常见重放错误：`RUN_NOT_FOUND`（404）、游标格式/冲突（422）、`INVALID_EVENT_CURSOR` 或 `EVENT_HISTORY_GAP`（409）、`REPLAY_BUSY`（429）。模型协议失败和工具拒绝仍返回明确诊断结果。

## 评测

20 道诊断案例复用诊断运行时。自动规则检查工具轨迹、参数、Evidence 身份和报告引用。人工语义审核单独检查报告中的根因与每条建议，并逐项标注所引用证据。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode mock --output eval_result_mock.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review-freeze `
  eval_result_real.json --cases samples/evaluation/cases.json `
  --references samples/evaluation/semantic_references.json --output eval_review_batch.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review `
  eval_review_batch.json --reviewer reviewer-a
```

配置模型变量后，使用 `--mode real` 评测真实模型。真实评测会记录模型请求消息和可见 Evidence ID。历史结果若未保存实际请求，会将模型可见范围标记为未知。冻结批次会绑定案例、参考标准、Run、模型配置、Prompt 指纹、样本与Evidence快照。历史批次无法证明原始 Prompt 指纹时，会标记为未验证。

| 指标 | 定义 |
| --- | --- |
| `rule_pass_rate` | 规则通过数 / 全部案例 |
| `semantic_quality.root_cause_support_rate` | 经裁决或当前可用审核记录中，根因标为完全支持的比例 |
| `semantic_quality.recommendation_evidence_support_rate` | 建议标为完全有证据支持的比例 |
| `semantic_quality.required_fact_coverage_rate` | 已覆盖的适用必需事实比例 |
| `semantic_quality.evidence_insufficient_correct_refusal_rate` | 证据不足案例中，审核者认为回答行为合适的比例 |

报告 Claim 缺失的 Run 仅参与执行契约评测，不进入Claim质量分母。双评审分歧单独统计，仲裁前不进入质量指标。只有一名评审时明确报告单人审核，不计算评审一致性。无真实冲突观测的场景列为覆盖缺口，不用合成结果代替。导出与导入 JSON 审核模板可用于异步评审，导入时会校验批次绑定、Run、Claim、Evidence、参考事实和理由。

完整的评审与JSON导入流程见 [docs/evaluation-human-review-v1.md](docs/evaluation-human-review-v1.md)。Mock 验证工程行为，不能代表真实模型准确率。

## 测试

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider
```

覆盖领域规则、工具、模型、持久化、评测、流式、预算、取消、重放和启动收尾。PostgreSQL 测试需显式启用：配置数据库变量，pytest 前设置 `EVIDENCEOPS_TEST_POSTGRES='1'`，结束后移除。实验使用隔离 schema 和测试锁键。真实模型验收与确定性回归分开执行。

前端检查：

```powershell
cd frontend
npm test
npm run typecheck
npm run build
```

日志解析器在 `cpp/log_evidence_engine/` 下独立构建，要求 C++20 编译器、CMake 3.20 或更高版本，以及 CLI 契约测试所需的 Python 3：

```powershell
cd cpp/log_evidence_engine
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

Playwright CLI 场景覆盖诊断、取消、重连、历史、证据、模型管理、安装、备份恢复、故障、文件竞态、键盘交互及 320～1440 像素布局。测试需隔离的 3011/8011 和 3015/8015 服务、确定性模型，以及首次设置用的全新安装目录。写入与恢复场景不能指向客户数据。[测试报告](frontend/FRONTEND_TEST_REPORT.md)保留具体日期的验证证据及边界。

`frontend/tests/serve_backend.py` 提供隔离后端工厂；`EVIDENCEOPS_BROWSER_TEST_ROOT` 指定全新测试目录。普通场景使用网页 3011 / API 8011；安装场景使用网页 3015 / API 8015，并让两端使用同一全新数据目录。安装场景以 `create_installed_app` 配合 `build_test_app` 工厂启动。测试模型不请求供应商，故障和延迟仅在测试供应商中注入。

准备上述服务后，在根目录执行：

```powershell
npx.cmd --yes --package @playwright/cli playwright-cli -s=evidenceops open http://127.0.0.1:3011 --browser msedge
.venv/Scripts/python.exe frontend/tests/run_browser_audit.py
```

首次设置场景需要尚未初始化的目录。可回归指定组，如 `run_browser_audit.py failures audit-regressions`。结果、日志、截图和隔离数据库写入已忽略的 `output/playwright/`。

## 贡献约定

领域规则与模型/数据库适配器及前端传输层分离。修改附带相关失败路径测试，并同步中英文接口与配置说明。不提交凭据、本机数据库或生成的评测结果。Python 依赖清单固定直接依赖，前端安装使用 `package-lock.json`。开发环境搭建、测试命令与 PR 检查清单见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全

疑似安全漏洞请勿公开提交 issue，上报渠道见 [SECURITY.md](SECURITY.md)。

## 许可证

本项目基于 [Apache License 2.0](LICENSE) 发布。
