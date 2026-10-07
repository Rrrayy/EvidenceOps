# EvidenceOps

<p align="center">
  <strong>Evidence-driven diagnosis for backend incidents</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">中文</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#architecture">Architecture</a>
</p>

EvidenceOps is an agent platform for diagnosing backend failures with traceable evidence. It is designed around a simple rule: a model may propose a hypothesis, but every report conclusion must be supported by evidence collected through controlled tools.

The first target scenario is C++ RPC timeout and thread-pool exhaustion. The project is built from the runtime boundary outward, so model providers, tool execution, evidence collection, and report validation remain independently testable.

## Why EvidenceOps

Incident diagnosis usually requires correlating logs, RPC failures, queue depth, thread-pool metrics, configuration, and deployment context. A chat response alone cannot show which facts support a conclusion, and an unconstrained agent can call the wrong function or accept malformed parameters.

EvidenceOps makes those boundaries explicit:

- models request tools; they do not execute application functions directly;
- tools pass through registration, schema, timeout, and execution checks;
- tool results become typed `Evidence` objects;
- structured model output becomes a validated diagnosis draft;
- reports bind root causes and recommendations to `Evidence ID` values.

## Architecture

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

The runtime and provider paths are deliberately separated:

```text
ModelRequest -> LLMGateway -> Provider -> ProviderResponse
                                      -> ModelCallResult
                                      -> AgentLoop

ToolCall -> ToolRuntime -> ToolResult -> Evidence
```

## Core boundaries

| Layer | Responsibility |
| --- | --- |
| Domain | `DiagnosisRun`, `Evidence`, and evidence-backed `DiagnosisReport` rules |
| Application | diagnosis orchestration, agent loop, model protocol, gateway, draft validation, and report building |
| Infrastructure | model provider adapters and external integrations |
| API | HTTP response conversion and the current mock diagnosis endpoint |
| Mocks | deterministic RPC timeout, request-log, thread-pool, and provider scenarios |

## Implemented foundation

- typed diagnosis lifecycle with explicit failure codes;
- immutable evidence objects with source, observation time, location, and fingerprint validation;
- tool registry/runtime boundary with parameter checks, timeout handling, and stable tool errors;
- mock agent loop with `tool_call_id` pairing and deterministic results;
- provider-independent model protocol and LLM gateway;
- mock provider and OpenAI-compatible provider adapter;
- explicit Mock/OpenAI-compatible provider selection through environment variables;
- provider URL validation, timeout classification, and upstream error propagation;
- standard Chat Completions tool-call history and JSON-object model responses;
- `DiagnosisDraft` validation before report construction;
- report-level validation that evidence IDs exist and belong to the current run;
- FastAPI response mapping for JSON and the Agent diagnosis workflow;
- a real Qwen model connected to the Agent HTTP path with local read-only log, metric, and historical configuration Connectors;
- multi-tool responses with bounded concurrent execution and `tool_call_id` correlation;
- model/tool execution records returned with each diagnosis for latency and failure inspection;
- bounded concurrent execution for a batch of tool calls;
- PostgreSQL persistence for `diagnosis_runs`, `evidences`, `diagnosis_reports`, and `execution_records`, managed with Alembic;
- historical diagnosis retrieval through `GET /api/v1/agent/runs/{run_id}` without invoking the model again.

## Quick start

Use Python 3.14 and run the test suite from the repository root:

```powershell
$env:PYTHONPATH="src"
python -m pytest
```

The repository uses deterministic local JSONL fixtures for repeatable evidence tests while allowing a real OpenAI-compatible model Provider. Provider credentials are supplied through environment variables; PostgreSQL persistence is now integrated, while SSE streaming and production log/metric/configuration platforms remain follow-up work.

For the current Qwen-compatible endpoint, configure the Provider before starting the API:

```powershell
$env:EVIDENCEOPS_PROVIDER="openai-compatible"
$env:EVIDENCEOPS_MODEL_BASE_URL="https://maas.qianwenaiapi.com/compatible-mode/v1"
$env:EVIDENCEOPS_MODEL_API_KEY="your-api-key"
$env:EVIDENCEOPS_MODEL_NAME="qwen3.8-flash"
$env:EVIDENCEOPS_MODEL_TIMEOUT_SECONDS="60"
$env:EVIDENCEOPS_PERSISTENCE="postgres"
$env:POSTGRES_PASSWORD="your-postgres-password"
```

Start PostgreSQL and apply migrations before starting the API:

```powershell
docker compose up -d
$env:PYTHONPATH="src"
python -m alembic upgrade head
```

The API exposes `POST /api/v1/agent/diagnosis`. The current end-to-end path can use a real model with three local read-only Connectors; the returned report must reference Evidence IDs produced during that run. The response also includes bounded execution records for the model rounds and tool calls. After a diagnosis completes, `GET /api/v1/agent/runs/{run_id}` retrieves the persisted result without invoking the model again.

## Example contract

A model tool request is represented inside the runtime rather than passed directly to a local handler:

```python
ToolCall(
    tool_call_id="call_001",
    tool_name="collect_thread_pool_metrics",
    arguments={"service_name": "order-service"},
)
```

After runtime validation and execution, the result is converted into an evidence record. A structured final answer is parsed into a `DiagnosisDraft`; the report builder then injects the current run ID and validates every referenced evidence ID.

## Design principles

1. Evidence before confidence.
2. The model has proposal rights, not execution rights.
3. Protocol validation and business validation are separate boundaries.
4. Failure, timeout, and malformed model output are first-class results.
5. The self-built runtime owns state, policy, evidence binding, and audit semantics.

## Development

The project is developed in small, testable slices. Each integration follows the same path: understand the business failure, define the boundary, implement the smallest deterministic behavior, verify normal and failure paths, then connect the next layer.

Detailed learning notes and the evolving engineering plan are kept separately from this public-facing overview.

## License

License information will be added before the first public release.
