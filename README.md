# EvidenceOps

EvidenceOps 是一个面向 C++ 后端和分布式服务的证据驱动故障诊断 Agent 平台。

它接收故障描述、应用日志和运行环境信息，通过受控的只读工具收集日志、指标和配置证据，由 Agent Runtime 组织诊断过程，最后生成带 Evidence ID 引用的诊断报告。

EvidenceOps 不把模型输出直接当作事实，也不允许模型直接执行本地函数。模型只能提出工具调用请求，平台负责工具注册、参数校验、权限、运行时策略、超时、取消、审计和结果校验。

## 项目要解决的问题

后端故障通常需要同时查看：

- 应用日志和错误堆栈；
- RPC 超时和重试记录；
- 线程池、连接池和队列指标；
- 服务配置和最近部署记录；
- 历史故障文档和处理经验。

这些信息分散在不同系统中，人工排查容易遗漏时间关系，也很难回答“这个结论依据了哪些事实”。普通的聊天式 Agent 还存在两个问题：模型可能无证据猜测，工具调用可能缺少权限和副作用控制。

EvidenceOps 的核心目标是把故障诊断变成可追踪的证据分析过程：

```text
故障现象
→ 受控收集证据
→ 形成诊断假设
→ 验证假设
→ 生成带引用的结论
→ 保存完整运行轨迹
```

## 第一版范围

第一版只聚焦一个真实场景：

```text
C++ RPC 服务超时与线程池耗尽诊断
```

### 输入

- 故障描述；
- 应用日志；
- 服务名称；
- 运行环境；
- 可选的时间范围。

### 处理

- 创建一次独立的 `DiagnosisRun`；
- 解析日志并生成 `Evidence`；
- 通过只读工具查询模拟指标、配置和部署信息；
- 使用 Agent Runtime 组织有限步骤的诊断；
- 将每条诊断结论绑定到一个或多个 `Evidence ID`；
- 保存运行记录、证据、工具调用、Trace 和诊断报告；
- 通过普通 JSON 和 SSE 返回结果。

### 第一版明确不做

- 不自动重启服务；
- 不修改线上配置；
- 不删除数据；
- 不执行任意 Shell 命令；
- 不做多租户计费；
- 不做多 Agent 协作；
- 不一开始接入全部 RAG、MCP 和框架能力。

第一版的工具全部是只读工具。只读不是文档约定，而是运行时策略：非只读工具在进入 handler 之前就被策略层拒绝。

## 总体架构

```text
                         +----------------------+
                         |      Web Client       |
                         |  HTTP / SSE / JSON    |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |   Agent API Gateway   |
                         | FastAPI / Request ID  |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |  Diagnosis Service   |
                         | Use Case / Validation|
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |    Agent Runtime     |
                         | State / Budget / Loop|
                         +----+------------+----+
                              |            |
                              v            v
                    +----------------+  +----------------+
                    |  LLM Gateway   |  |  Tool Registry |
                    | Provider/Cost  |  | Schema/Policy  |
                    +--------+-------+  +--------+-------+
                             |                   |
                             v                   v
                       Model API         Evidence Connectors
                                                 |
                          +----------------------+------------------+
                          |                  |                     |
                          v                  v                     v
                       Logs              Metrics                Config

              PostgreSQL: runs / evidence / reports / Trace
```

## 数据流

```text
1. 客户端提交故障描述和日志。
2. API Gateway 校验请求并生成 request_id。
3. Diagnosis Service 创建 DiagnosisRun。
4. Agent Runtime 读取请求上下文并设置预算。
5. 模型提出只读工具调用请求。
6. Tool Registry 校验工具、参数、权限和运行时策略。
7. Evidence Connector 查询数据并生成 Evidence。
8. Runtime 将工具结果和 Evidence 追加到诊断上下文。
9. 模型形成根因假设和建议。
10. Diagnose 校验结构化报告和 Evidence 引用。
11. Persistence 保存运行、工具、证据、Trace 和报告。
12. API 通过 JSON 或 SSE 返回结果。
```

## 核心设计原则

### 证据优先

每条根因和建议都必须能够关联 Evidence ID。模型可以提出假设，但不能把没有来源的猜测直接写成事实。

### 模型没有执行权

模型只能请求工具。后端通过 Tool Registry 和 Policy Engine 决定工具是否存在、参数是否合法、调用者是否有权限以及当前运行是否允许执行。

### Runtime 自研，通用能力借鉴框架

Agent 的状态、预算、工具策略、Evidence 绑定、审计和错误协议由 EvidenceOps 自己控制。LangChain、LangGraph、LlamaIndex、LangSmith 和 AutoGen 只在对应需求出现时通过实验和 Adapter 引入。

### 失败也是协议的一部分

模型超时、工具失败、参数错误、策略拒绝、证据不足和客户端断开都必须有明确状态、错误码和清理路径。不能只为成功请求设计流程。

### 运行可回放

一次诊断需要记录模型调用、工具调用、证据收集、状态迁移和最终报告，使开发者能够解释结果、复现问题和比较版本。

## V1 模块边界

| 模块 | V1 职责 | V1 不负责 |
|---|---|---|
| API Gateway | 请求校验、request_id、JSON/SSE、HTTP 错误 | 模型调用、工具执行 |
| Diagnosis Service | 组织诊断用例、调用 Runtime、校验报告 | 供应商 HTTP 细节 |
| Agent Runtime | messages、状态、预算、循环、取消和事件 | 具体日志查询实现 |
| LLM Gateway | Provider、超时、usage、成本和模型错误 | 执行本地函数 |
| Tool Registry | 工具声明、Schema、权限、版本和策略 | 生成最终诊断结论 |
| Evidence Connector | 查询日志、指标、配置并生成 Evidence | 决定是否接受根因 |
| Diagnose | 报告结构和业务规则、Evidence 引用校验 | HTTP 和数据库连接管理 |
| Persistence | 保存运行、证据、Trace 和报告 | 代替 Runtime 做状态决策 |

## V1 技术栈

- Python 3.14；
- FastAPI、Pydantic、asyncio、httpx；
- PostgreSQL；
- SQLAlchemy 或 SQLModel；
- Alembic；
- pytest；
- Docker Compose；
- Mock Provider 和 OpenAI-compatible Provider；
- SSE；
- 自研 TraceEvent。

Redis、pgvector、MCP、OpenTelemetry、LangSmith、LangGraph 和 Kubernetes 会在项目产生真实需求后按版本引入。

## 领域对象

### DiagnosisRun

一次完整诊断请求，保存 `request_id`、状态、用户输入、开始/结束时间和错误信息。

### Evidence

一条可以支持诊断判断的事实，保存来源、时间、内容摘要、来源引用、版本和哈希。

### ToolInvocation

一次模型工具请求和实际执行记录，保存 `tool_call_id`、工具版本、参数摘要、策略决策、执行状态和错误。

### TraceEvent

一次运行事件，保存 `run_id`、递增序号、事件类型、状态、耗时和脱敏后的摘要。

### DiagnosisReport

最终诊断报告，至少包含根因、置信度、Evidence 引用、建议和限制说明。

## 版本路线

### V1：证据诊断 MVP

实现单租户、PostgreSQL、三个只读 Evidence Connector、自研 Agent Runtime、普通 JSON、SSE 和基础 Trace。

验收：输入一个脱敏 C++ RPC 故障案例，系统能收集证据，生成带 Evidence ID 的报告，保存到 PostgreSQL，并通过测试验证正常、失败、超时和取消路径。

### V1.5：可靠性与可观测性

根据 V1 的真实问题引入 Token/成本统计、硬预算、Redis、Policy Engine、审计、OpenTelemetry 和最小 Replay。

### V2：知识增强与企业工具集成

根据历史故障文档需求引入 pgvector 混合检索、RAG 评测、MCP OAuth 2.0、动态工具发现和断线恢复，并用 LangGraph 与 LangChain 做对照实现。

### V3：平台化

引入 Kubernetes、Worker、灰度发布、Prometheus/Grafana、多租户、RBAC 和更完整的 Trace/Evaluation。

## 学习方式

每个新技术都遵循同一个闭环：

```text
EvidenceOps 出现真实问题
→ 学习最小必要原理
→ 写独立实验验证机制
→ 从零接入 EvidenceOps
→ 正常测试
→ 失败测试
→ 故障注入
→ 更新文档和复盘
```

学习仓库用于验证概念，EvidenceOps 用于重新设计生产级实现。可以借鉴架构思想，不能直接复制学习仓库的具体代码。

## 当前状态

```text
项目状态：V1 领域层已起步，Diagnosis Service 尚未实现
已完成：DiagnosisRun、Evidence、DiagnosisReport；领域测试 11 passed
下一步：使用 Mock 依赖实现最小 Diagnosis Service 闭环
```
