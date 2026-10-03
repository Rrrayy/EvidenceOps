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
- text and JSON-object model responses;
- `DiagnosisDraft` validation before report construction;
- report-level validation that evidence IDs exist and belong to the current run;
- FastAPI response mapping for JSON and the mock diagnosis workflow.

## Quick start

Use Python 3.14 and run the test suite from the repository root:

```powershell
$env:PYTHONPATH="src"
python -m pytest
```

The repository currently uses deterministic mocks for the learning and integration boundary. Provider credentials, PostgreSQL persistence, real evidence connectors, and the production HTTP path are intentionally introduced as separate steps.

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
