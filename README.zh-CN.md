# EvidenceOps

<p align="center">
  <strong>面向多语言软件故障的证据驱动诊断 Agent</strong>
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#架构">架构</a>
</p>

EvidenceOps 是一个面向常见语言和后端技术栈的软件故障诊断 Agent 平台。用户可以提交故障描述、错误日志、异常堆栈、配置或代码上下文，Agent 会收集受控证据，区分已确认事实与推测，并生成可追溯的诊断报告。

项目并不只服务 C++。第一批计划支持 Python、Java、Go、JavaScript/TypeScript 和 C/C++，之后再支持 Rust、PHP 和 C#。当前的 RPC 超时样本是用于训练和集成验证的确定性数据，不是产品边界。

## 项目简介

## 为什么做 EvidenceOps

一次软件故障排查通常需要关联日志、异常堆栈、源代码上下文、指标、配置、部署记录和技术文档。单纯的自然语言回复无法说明结论依据了哪些事实；没有边界的 Agent 也可能调用错误函数或接受不合法参数。

EvidenceOps 将这些边界明确化：

- 模型只能请求工具，不能直接执行业务函数；
- 工具必须经过注册、参数 Schema、超时和执行检查；
- 工具结果转换为类型化的 `Evidence`；
- 结构化模型输出先转换并校验为诊断草稿；
- 报告中的根因和建议必须绑定 `Evidence ID`。

## 功能特性

- 与模型 Provider 解耦的 Agent Loop 和 OpenAI-compatible 模型适配器。
- 多个只读工具的受限并发执行。
- 带来源、观测时间、位置、版本和内容哈希的 Evidence 收集。
- 结构化报告校验和 Evidence 引用归属校验。
- 使用 Alembic 管理迁移的 PostgreSQL 持久化。
- 不重新调用模型的历史 Run 查询接口。
- SSE 生命周期事件、共享执行预算和单进程显式取消。
- 20 案例离线 Eval、规则检查、CLI 人工审核和通过率持久化。

## 架构

```text
                    Diagnosis Service
                           |
                           v
                     Agent Runtime
                 +---------+---------+
                 |                   |
                 v                   v
            LLM Gateway         Tool Runtime
                 |                   |
                 v                   v
             Provider         Evidence Collector
                 |                   |
                 +---------+---------+
                           v
                    Evidence + Draft
                           |
                           v
                 Validated Diagnosis Report
```

运行时调用顺序与依赖构造顺序分开。未来的语言适配器会把不同语言的错误统一成诊断上下文，因此 Agent Runtime 不需要为每种语言复制一套实现：

```text
ModelRequest -> LLMGateway -> Provider -> ProviderResponse
                                      -> ModelCallResult
                                      -> AgentLoop

ToolCall -> ToolRuntime -> ToolResult -> Evidence

原始输入 -> 语言/框架识别 -> 解析器适配器 -> ParsedError -> Evidence -> Agent Runtime
```

## 核心边界

| 层 | 职责 |
| --- | --- |
| Domain | `DiagnosisRun`、`Evidence` 和报告证据引用规则 |
| Application | 诊断编排、Agent Loop、模型协议、Gateway、草稿校验和报告构建 |
| Infrastructure | 模型 Provider 适配器和外部集成 |
| API | HTTP 响应转换和 Agent 诊断入口 |
| 输入适配器 | 未来的语言和框架解析器，输出统一诊断上下文 |
| Mocks | RPC 超时、请求日志、线程池和 Provider 的确定性场景 |

## 已实现基础

- 带明确失败错误码的诊断生命周期；
- 带来源、观测时间、来源位置和指纹校验的不可变证据对象；
- 带参数检查、超时处理和稳定错误协议的 Tool Runtime 边界；
- 支持 `tool_call_id` 配对和确定性结果的 Mock Agent Loop；
- 与 Provider 解耦的模型协议和 LLM Gateway；
- Mock Provider 与 OpenAI-compatible Provider 适配器；
- 通过环境变量显式选择 Mock 或 OpenAI-compatible Provider；
- Provider URL 校验、超时分类和上游错误传递；
- 标准 Chat Completions 工具调用历史和 JSON Object 响应；
- 报告构建前的 `DiagnosisDraft` 校验；
- 报告级 Evidence ID 存在性和当前 run 归属校验；
- Agent 诊断流程的 FastAPI 响应转换；
- 真实 Qwen 模型接入 Agent HTTP 主链，并接入本地只读日志、指标和历史配置 Connector；
- 支持一轮多个工具调用、受限并发执行和 `tool_call_id` 结果配对；
- HTTP 响应返回模型与工具执行记录，用于检查耗时、参数和失败位置；工具批次支持受限并发。
- PostgreSQL 持久化 `diagnosis_runs`、`evidences`、`diagnosis_reports` 和 `execution_records`，并通过 Alembic 管理迁移。
- 支持通过 `GET /api/v1/agent/runs/{run_id}` 查询已完成或失败的历史诊断，不会重新调用模型。
- 20案例离线Eval，支持Mock/真实模型、规则检查、CLI人工审核和三项通过率回写。

## 技术栈

- Python 3.14
- FastAPI 与 Pydantic
- SQLAlchemy、Alembic 与 PostgreSQL 17
- Psycopg 3
- Docker Compose
- pytest
- OpenAI-compatible 模型接口

后续学习和集成路线包括 PostgreSQL/pgvector RAG、LangChain Adapter、LangGraph 对照实现、MCP 和 OpenTelemetry。在完成实现和测试前，不把这些内容写成已完成能力。

## 快速开始

使用 Python 3.14，在仓库根目录执行测试：

```powershell
$env:PYTHONPATH="src"
python -m pytest
```

当前仓库使用本地 JSONL 样本提供可重复的只读证据查询，同时支持真实 OpenAI-compatible 模型 Provider。Provider 凭据通过环境变量提供；PostgreSQL 持久化、Eval 和 SSE 过程事件已接入。用户已完成一次真实模型加 PostgreSQL 的流式成功验证；生产日志、指标和配置平台仍待接入。

当前 Qwen 兼容接口的配置方式：

```powershell
$env:EVIDENCEOPS_PROVIDER="openai-compatible"
$env:EVIDENCEOPS_MODEL_BASE_URL="https://maas.qianwenaiapi.com/compatible-mode/v1"
$env:EVIDENCEOPS_MODEL_API_KEY="your-api-key"
$env:EVIDENCEOPS_MODEL_NAME="qwen3.8-flash"
$env:EVIDENCEOPS_MODEL_TIMEOUT_SECONDS="120"
$env:EVIDENCEOPS_RUN_TIMEOUT_SECONDS="180"
$env:EVIDENCEOPS_PERSISTENCE="postgres"
$env:POSTGRES_PASSWORD="your-postgres-password"
```

启动 PostgreSQL 后先执行迁移：

```powershell
docker compose up -d
$env:PYTHONPATH="src"
python -m alembic upgrade head
```

API 接口为 `POST /api/v1/agent/diagnosis`。当前端到端流程可以使用真实模型和三个本地只读 Connector，返回报告必须引用本次运行实际生成的 Evidence ID；响应还包含模型轮次和工具调用的执行记录。诊断完成后，可以使用 `GET /api/v1/agent/runs/{run_id}` 从 PostgreSQL 查询历史结果。

## Eval：离线评测与人工审核

Eval直接复用DiagnosisService、AgentLoop和只读工具，不需要启动HTTP服务或PostgreSQL。固定题库包含20个案例：正常查询5个、无数据与证据不足4个、配置和时间边界4个、参数与服务边界4个、截断和推断边界3个。真实模式只向模型提供请求描述和工具定义，预期参数与人工标准留给评测器。

在项目根目录执行Mock工程验证：

```powershell
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode mock --output eval_result_20_mock.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review eval_result_20_mock.json
```

真实模式需要当前窗口配置模型Base URL、API Key与模型名，使用前文的模型环境变量；运行会产生API费用：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode real --output eval_result_20_real.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review eval_result_20_real.json
```

`--output`直接保存UTF-8，避免PowerShell文本管道转换破坏中文。重跑同一路径会替换结果及已有审核状态。review分段展示请求、模型根因、建议、局限与审核标准，输入y/n及可选comment；每条完成后保存，中断重运行只继续pending案例。

| 指标 | 定义 |
| --- | --- |
| rule_pass_rate | 规则通过数量 / 全部案例 |
| semantic_pass_rate | 人工审核passed数量 / 全部案例 |
| final_pass_rate | 同一案例规则和人工均通过数量 / 全部案例 |

异常及pending保留在总分母；预期拒绝的失败案例也可以评测通过。规则检查覆盖参数、执行状态、证据来源/摘要和引用归属，不自动证明证据语义支持结论。Mock证明工程链路，不能代替真实模型质量评测。

本地真实模型单批结果为18/20，三项均90%、pending=0；两例因最终输出协议失败，具体原始格式原因未确认，保留基线暂不复现。这不是生产诊断准确率。当前尚未汇总Token/成本、保存原始模型失败输出、实现运行中逐案例恢复或多审核人协作；API 已接入共享执行预算，Eval 不自动开启。题库与审核说明见 [Eval使用说明](samples/evaluation/README.md)。

## 后续进度

`POST /api/v1/agent/diagnosis/stream` 推送模型与工具的起止事件，保存完成后发出 `run_completed`、`run_failed` 或 `run_cancelled`。通过 `curl.exe -N` 配合 `--data-binary "@samples/requests/sse-diagnosis.json"` 发送样本请求。断开流不会自动取消诊断；事件持久化和GET重连补发已接入，重启恢复仍是后续工作。

### 事件持久化（迁移 0004）

postgres模式下，普通HTTP与SSE诊断都会将业务事件写入 `trace_events`，提交后再发送。终止事件与Run终态、Evidence、执行记录及成功报告共享事务。发送失败不影响已提交档案；数据库保存失败返回 `PERSISTENCE_FAILED`，SSE以没有事件ID的 `stream_failed` 结束，不能宣称终态已保存。memory模式仍仅提供内存事件。

升级数据库后再启动新版本API：

```powershell
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
docker compose exec -T postgres psql -U evidenceops -d evidenceops -c "SELECT run_id,sequence,event_type,occurred_at FROM trace_events ORDER BY occurred_at DESC LIMIT 20;"
```

需要先按现有数据库配置设置 `POSTGRES_PASSWORD`。本版不自动迁移public表。旧Run没有历史事件，不补造。进程崩溃可能丢失尚未提交的Evidence/执行记录；保存事件不等于执行检查点。事件内容包含报告和路径摘要，按业务数据管理，不复制到普通日志。取消请求事件也会保存，但不能据此自动恢复内存取消信号。

### 事件查询与断线重连

已有0004表时无需新迁移，只需重启API。创建诊断仍用POST；下列GET接口只观察已有Run，不调用模型或启动工具：

```powershell
$run_id=(Read-Host '粘贴已有run_id').Trim()
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/events?after=0&limit=5"
curl.exe -N "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/events/stream" -H "Last-Event-ID: ${run_id}:5"
```

JSON返回events、next_sequence、max_sequence、has_more及status，下一页把next_sequence传给after。GET流仅发送sequence大于游标的事件；不传游标从头开始，也可用 `?after=5`。请求头和after同时提供必须一致。已有终态补发后关闭，末尾游标只返回connected注释后关闭，旧终态Run无事件时返回空历史，不补造结果。浏览器EventSource收到终止事件应主动close，避免自动重试空的已结束流；本版curl不会自动重连，需要你保存最后ID后发起GET。

活跃流每0.5秒读取一页数据库事件，每页100条，15秒心跳。历史与新事件来自同一个数据库游标，没有内存订阅切换窗口。每进程最多16条重放观察连接，超额返回429 REPLAY_BUSY，断连释放观察槽但不取消Run。读取结束就关闭Session，发送或等待时不占数据库连接。memory模式返回503 PERSISTENCE_DISABLED；未知Run为404；格式错误/游标冲突为422；超过最大序号为409 INVALID_EVENT_CURSOR；发现序号缺口为409 EVENT_HISTORY_GAP。开流后读取失败发送无id的stream_failed。

本版没有清理事件，所以不实现410过期逻辑；客户端仍需按event_id去重。运行进程崩溃后遗留running暂时只会等待和心跳，启动恢复尚未实现，手工观察可加curl的 `--max-time`。

API 默认使用 180 秒共享执行预算，由 `EVIDENCEOPS_RUN_TIMEOUT_SECONDS` 配置。模型和工具每次等待取“单次超时与剩余预算的较小值”。预算耗尽返回 `RUN_TIMEOUT`；提前触发的单次超时仍是 `MODEL_TIMEOUT` 或 `TOOL_TIMEOUT`。修改环境变量后需重启 API。示例模型超时为 120 秒，未配置时仍默认 60 秒；直接使用组装器或 Eval 时，总预算需调用者显式开启。

这不是HTTP响应硬截止：API真实Provider现在用请求独立的异步HTTP任务，每约50毫秒检查取消与总预算，并取消和等待本地IO清理；同步第三方Provider仍只能在返回后检查。数据库提交、资源清理可能延长响应时间，已启动工具线程不能强杀。预算从DiagnosisService内部开始，不包含此前HTTP解析和接纳。确定性验证见 `tests/test_run_budget.py`。

## 显式取消（单进程）

重启API加载新代码，用SSE发送请求，在 `run_started` 中获取真实Run ID。另开PowerShell执行：

```powershell
$run_id=(Read-Host "粘贴正在执行的run_id").Trim()
curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/cancel"
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/$run_id"
```

202表示已接纳取消请求，不代表已落库；重复请求幂等。SSE先发 `run_cancel_requested`，终态保存后发 `run_cancelled`。历史最终应为 `status=cancelled`、`error_code=null`、`report=null`；已完成且验证的Evidence与记录保留，取消调用记录为 `status=cancelled / error_code=RUN_CANCELLED`。Run领域将取消作为独立终态，故不使用失败Run的error_code。

提交成功/失败已认领时返回409及 `phase=finalizing`，不承诺提交已成功；持久化已结束Run返回200和现有终态，不改变它。未知ID返回404；数据库仍running但当前进程没有登记的Run返回409 `RUN_NOT_ACTIVE`，不伪造取消成功。memory模式无已结束历史，因此结束后再取消可能404。

每Run独立Event与锁，Service统一认领终态。模型请求取消只清理本地IO，不保证供应商停止生成或计费。本地三个JSONL Connector支持逐行协作取消并关闭文件；其他handler可声明 `controlled_handler(arguments,control)`，用 `control.check()` 与 `control.wait(seconds)` 响应。未配合的运行线程可能继续占handler池槽，迟到结果不进入报告；不能把Run已取消当作全部线程已停止。

登记表只在当前进程内，启动时不要设置多个workers；本版不支持跨worker/跨主机取消、取消意图持久化或重启恢复。模型可取消路径使用每次请求独立AsyncClient/事件循环，减少对现有同步编排的改动，但不复用跨轮HTTP连接池。显式注入同步client且未提供async_client_factory时保留原客户端，仅支持调用前后检查，不能中断其同步IO。测试不要求真实模型额度：

```powershell
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_run_cancellation.py -q -p no:cacheprovider
```

取消专项覆盖API、SSE、SQLAlchemy+SQLite历史回查、两Run隔离、终态竞争、真实localhost TCP读取取消、排队工具、协作/非协作handler及Connector文件关闭。真实供应商与PostgreSQL的取消手工验收另行执行。

## 路线图

- [x] Agent Loop、Tool Runtime、Evidence 校验和结构化报告。
- [x] 真实 OpenAI-compatible 模型链路和受限多工具并发。
- [x] Run、Evidence、报告和执行记录的 PostgreSQL 持久化。
- [x] SSE 生命周期事件、共享预算、超时处理和单进程取消。
- [x] 20 案例离线 Eval 和 CLI 语义审核。
- [x] 业务事件持久化，终态与终止事件原子提交。
- [x] 分页事件查询和断线后的 `Last-Event-ID` 补发。
- [ ] 服务重启后恢复未完成或可恢复的 Run。
- [ ] 学习并实现最小 RAG 链路：文档摄取、混合检索和 Evidence 引用。
- [ ] 增加 Python、Java、Go、JavaScript/TypeScript 和 C/C++ 的语言与框架适配器。
- [ ] 在第一批适配器评测稳定后增加 Rust、PHP 和 C#。
- [ ] 增加 LangChain 与 LangGraph 对照适配，不替换自研核心。
- [ ] 增加 MCP、OpenTelemetry、跨 Worker 协调和生产安全控制。

## 贡献说明

项目按小步、可测试的功能推进。每次修改都应明确边界，实现可确定的正常与失败路径，补充针对性测试，并同步更新相关文档。不要将密钥和生成的评测结果提交到 Git。

## 设计原则

1. 先有证据，再谈置信度。
2. 模型拥有提议权，不拥有执行权。
3. 协议校验和业务校验分层处理。
4. 失败、超时和模型格式错误都是正式结果。
5. 状态、策略、证据绑定和审计语义由自研 Runtime 控制。

## 开发说明

项目按小步、可验证的功能推进。每次集成都遵循：先理解真实业务故障，再定义边界，实现最小确定性行为，验证正常和失败路径，最后连接下一层。

详细学习笔记和持续演进的工程规划与本首页分开维护。

## License

首个公开版本发布前补充许可证信息。

## 致谢

- [Best-README-Template](https://github.com/othneildrew/Best-README-Template)：README 章节组织参考。
- FastAPI、PostgreSQL、SQLAlchemy、Alembic、pytest 和 OpenAI-compatible 生态。
