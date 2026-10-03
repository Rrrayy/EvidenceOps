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
| API | HTTP 响应转换和当前 Mock 诊断入口 |
| Mocks | RPC 超时、请求日志、线程池和 Provider 的确定性场景 |

## 已实现基础

- 带明确失败错误码的诊断生命周期；
- 带来源、观测时间、来源位置和指纹校验的不可变证据对象；
- 带参数检查、超时处理和稳定错误协议的 Tool Runtime 边界；
- 支持 `tool_call_id` 配对和确定性结果的 Mock Agent Loop；
- 与 Provider 解耦的模型协议和 LLM Gateway；
- Mock Provider 与 OpenAI-compatible Provider 适配器；
- 文本响应和 JSON Object 响应；
- 报告构建前的 `DiagnosisDraft` 校验；
- 报告级 Evidence ID 存在性和当前 run 归属校验；
- 当前 Mock 诊断流程的 FastAPI 响应转换。

## 快速开始

使用 Python 3.14，在仓库根目录执行测试：

```powershell
$env:PYTHONPATH="src"
python -m pytest
```

当前仓库使用确定性 Mock 验证学习和集成边界。Provider 凭据、PostgreSQL 持久化、真实 Evidence Connector 和生产 HTTP 主链会按独立阶段接入。

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
