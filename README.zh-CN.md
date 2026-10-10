# EvidenceOps

<p align="center">
  <strong>面向后端故障的证据驱动诊断 Agent</strong>
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#架构">架构</a>
</p>

EvidenceOps 是一个面向后端故障诊断的 Agent 平台。它遵循一条核心规则：模型可以提出诊断假设，但报告中的每条结论都必须由受控工具收集的证据支持。

第一阶段聚焦 C++ RPC 超时和线程池耗尽场景。项目从运行时边界开始构建，让模型 Provider、工具执行、证据收集和报告校验都可以独立测试。

## 为什么做 EvidenceOps

一次后端故障排查通常需要关联日志、RPC 错误、队列长度、线程池指标、配置和部署信息。单纯的聊天回复无法说明结论依据了哪些事实；没有边界的 Agent 也可能调用错误函数或接受不合法参数。

EvidenceOps 将这些边界明确化：

- 模型只能请求工具，不能直接执行业务函数；
- 工具必须经过注册、参数 Schema、超时和执行检查；
- 工具结果转换为类型化的 `Evidence`；
- 结构化模型输出先转换并校验为诊断草稿；
- 报告中的根因和建议必须绑定 `Evidence ID`。

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

运行时调用顺序与依赖构造顺序分开：

```text
ModelRequest -> LLMGateway -> Provider -> ProviderResponse
                                      -> ModelCallResult
                                      -> AgentLoop

ToolCall -> ToolRuntime -> ToolResult -> Evidence
```

## 核心边界

| 层 | 职责 |
| --- | --- |
| Domain | `DiagnosisRun`、`Evidence` 和报告证据引用规则 |
| Application | 诊断编排、Agent Loop、模型协议、Gateway、草稿校验和报告构建 |
| Infrastructure | 模型 Provider 适配器和外部集成 |
| API | HTTP 响应转换和 Agent 诊断入口 |
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

`POST /api/v1/agent/diagnosis/stream` 推送模型与工具的起止事件，保存完成后发出 `run_completed` 或 `run_failed`。通过 `curl.exe -N` 配合 `--data-binary "@samples/requests/sse-diagnosis.json"` 发送样本请求。断开流不会自动取消诊断；取消、重连补发、事件持久化与重启恢复仍是后续工作。

API 默认使用 180 秒共享执行预算，由 `EVIDENCEOPS_RUN_TIMEOUT_SECONDS` 配置。模型和工具每次等待取“单次超时与剩余预算的较小值”。预算耗尽返回 `RUN_TIMEOUT`；提前触发的单次超时仍是 `MODEL_TIMEOUT` 或 `TOOL_TIMEOUT`。修改环境变量后需重启 API。示例模型超时为 120 秒，未配置时仍默认 60 秒；直接使用组装器或 Eval 时，总预算需调用者显式开启。

这是协作式执行预算，不是 HTTP 响应硬截止：同步 HTTP 的阶段超时、同步数据库提交可能超出剩余预算，已启动工具线程不能强杀。检查点拒绝迟到结果，最终保存允许完成。预算从 DiagnosisService 内部开始计时，不包含此前 HTTP 解析和接纳过程。确定性失败验证见 `tests/test_run_budget.py`。

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
