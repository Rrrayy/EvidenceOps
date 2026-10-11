# EvidenceOps

<p align="center">
  <strong>Evidence-driven diagnosis for multilingual software incidents</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">中文</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#architecture">Architecture</a>
</p>

EvidenceOps is an Agent platform for diagnosing software failures across common language and backend stacks. Users can provide an incident description, error log, stack trace, configuration, or code context. The Agent collects controlled evidence, separates confirmed facts from hypotheses, and produces a traceable diagnosis report.

The project is not limited to C++. The first planned language adapters target Python, Java, Go, JavaScript/TypeScript, and C/C++; Rust, PHP, and C# are planned next. The current RPC timeout fixtures are deterministic training and integration data, not the product boundary.

## About The Project

## Why EvidenceOps

Incident diagnosis usually requires correlating logs, stack traces, source context, metrics, configuration, deployment history, and technical documentation. A natural-language answer alone cannot show which facts support a conclusion, and an unconstrained Agent can call the wrong function or accept malformed parameters.

EvidenceOps makes those boundaries explicit:

- models request tools; they do not execute application functions directly;
- tools pass through registration, schema, timeout, and execution checks;
- tool results become typed `Evidence` objects;
- structured model output becomes a validated diagnosis draft;
- reports bind root causes and recommendations to `Evidence ID` values.

## Features

- Provider-independent Agent Loop and OpenAI-compatible model adapter.
- Bounded concurrent execution of multiple read-only tools.
- Evidence collection with source, observation time, location, version, and content hash.
- Structured report and Evidence-reference validation.
- PostgreSQL persistence with Alembic migrations.
- Historical Run API without invoking the model again.
- SSE lifecycle events, shared execution budgets, and explicit single-process cancellation.
- 20-case offline Eval suite with rule checks, CLI human review, and persisted pass-rate metrics.

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

The runtime and provider paths are deliberately separated. Future language adapters will normalize language-specific failures into a shared diagnostic context, so the Agent Runtime does not need one implementation per language:

```text
ModelRequest -> LLMGateway -> Provider -> ProviderResponse
                                      -> ModelCallResult
                                      -> AgentLoop

ToolCall -> ToolRuntime -> ToolResult -> Evidence

Raw input -> Language/Framework Detector -> Parser Adapter -> ParsedError -> Evidence -> Agent Runtime
```

## Core boundaries

| Layer | Responsibility |
| --- | --- |
| Domain | `DiagnosisRun`, `Evidence`, and evidence-backed `DiagnosisReport` rules |
| Application | diagnosis orchestration, agent loop, model protocol, gateway, draft validation, and report building |
| Infrastructure | model provider adapters and external integrations |
| API | HTTP response conversion and the current mock diagnosis endpoint |
| Input adapters | future language and framework parsers that produce a shared diagnostic context |
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
- historical diagnosis retrieval through `GET /api/v1/agent/runs/{run_id}` without invoking the model again;
- a 20-case offline Eval suite with Mock/real modes, rule checks, CLI human review, and three persisted pass-rate metrics.

## Built With

- Python 3.14
- FastAPI and Pydantic
- SQLAlchemy, Alembic, and PostgreSQL 17
- Psycopg 3
- Docker Compose
- pytest
- OpenAI-compatible model APIs

Planned learning and integration tracks include RAG with PostgreSQL/pgvector, a LangChain adapter, a LangGraph comparison, MCP, and OpenTelemetry. They are not represented as completed features until implemented and tested.

## Quick start

Use Python 3.14 and run the test suite from the repository root:

```powershell
$env:PYTHONPATH="src"
python -m pytest
```

The repository uses deterministic local JSONL fixtures for repeatable evidence tests while allowing a real OpenAI-compatible model Provider. Provider credentials are supplied through environment variables; PostgreSQL persistence, Eval, and SSE process events are integrated. A user-run real-model/PostgreSQL streaming test succeeded; production log/metric/configuration platforms remain follow-up work.

For the current Qwen-compatible endpoint, configure the Provider before starting the API:

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

Start PostgreSQL and apply migrations before starting the API:

```powershell
docker compose up -d
$env:PYTHONPATH="src"
python -m alembic upgrade head
```

The API exposes `POST /api/v1/agent/diagnosis`. The current end-to-end path can use a real model with three local read-only Connectors; the returned report must reference Evidence IDs produced during that run. The response also includes bounded execution records for the model rounds and tool calls. After a diagnosis completes, `GET /api/v1/agent/runs/{run_id}` retrieves the persisted result without invoking the model again.

## Eval: offline evaluation and CLI review

Eval reuses DiagnosisService, AgentLoop, and the read-only tools without running the HTTP service or connecting to PostgreSQL. The fixed suite contains 20 cases: five normal queries, four empty-data/evidence-limit cases, four configuration/time boundaries, four parameter/service boundaries, and three truncation/inference boundaries. Real mode supplies the model with the request description and tool definitions; expected calls and review criteria stay with the evaluator.

Run Mock engineering checks from the repository root:

```powershell
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode mock --output eval_result_20_mock.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review eval_result_20_mock.json
```

Real mode requires the model Base URL, API key, and model name variables shown above in the current shell and incurs API charges:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode real --output eval_result_20_real.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review eval_result_20_real.json
```

`--output` writes UTF-8 directly, avoiding PowerShell text-pipeline encoding corruption. Reusing an output path replaces its results and review decisions. Review displays the request, root cause, recommendations, limitations, and criteria in separate sections. Enter y/n and an optional comment; each completed decision is saved, and restarting resumes pending cases.

| Metric | Definition |
| --- | --- |
| rule_pass_rate | Rule-passed cases / all cases |
| semantic_pass_rate | Human-reviewed passed cases / all cases |
| final_pass_rate | Cases passing both rules and human review / all cases |

Exceptions and pending cases remain in the denominator. Expected rejection cases can pass evaluation. Rules inspect arguments, execution status, evidence sources/summaries, and reference ownership; they do not automatically prove semantic support. Mock checks the engineering path, not real-model quality.

One local real-model batch scored 18/20 on all three metrics, with no pending reviews. Two cases failed the final-output protocol; their exact raw formatting defects remain unconfirmed, and the baseline is retained without reproduction for now. This is not production diagnosis accuracy. Token/cost aggregation, raw failed-model-output capture, per-case execution checkpoints, and multi-reviewer workflows are not implemented. The API now uses a shared execution budget; direct assembly and Eval callers remain opt-in. See the [Eval guide](samples/evaluation/README.md) for case details and review instructions.

## Follow-up status

`POST /api/v1/agent/diagnosis/stream` emits model/tool start and finish events, then `run_completed`, `run_failed`, or `run_cancelled` after persistence. Send `samples/requests/sse-diagnosis.json` with `curl.exe -N` and `--data-binary "@samples/requests/sse-diagnosis.json"`. Disconnecting the stream does not cancel the diagnosis. Durable events and GET replay are integrated; restart recovery remains follow-up work.

### Durable events (migration 0004)

In postgres mode, both ordinary HTTP and SSE diagnoses persist business events in `trace_events` before delivery. The terminal event shares a transaction with the Run status, Evidence, execution records, and successful report. Delivery failures do not invalidate committed data. Persistence failures return `PERSISTENCE_FAILED`; SSE ends with `stream_failed` without an event ID, rather than claiming a durable terminal state. Memory mode retains its in-memory behavior.

Apply migrations before starting the updated API, with `POSTGRES_PASSWORD` configured:

```powershell
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
docker compose exec -T postgres psql -U evidenceops -d evidenceops -c "SELECT run_id,sequence,event_type,occurred_at FROM trace_events ORDER BY occurred_at DESC LIMIT 20;"
```

The public schema is not automatically migrated. Old Runs are not backfilled. A crash can still lose uncommitted Evidence and execution records: a durable event log is not an execution checkpoint. Payloads contain business report/path summaries and must not be copied to ordinary logs. Cancellation-request events are durable, but cancellation signals are not restored from them.

### Event history and reconnect replay

With migration0004 already applied, restart the API; no new migration is required. POST creates a diagnosis; GET only observes an existing Run without invoking models or tools:

```powershell
$run_id=(Read-Host 'Paste an existing run_id').Trim()
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/events?after=0&limit=5"
curl.exe -N "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/events/stream" -H "Last-Event-ID: ${run_id}:5"
```

JSON pages expose events, next_sequence, max_sequence, has_more, and status. Pass next_sequence as after for the next page. The GET stream sends only sequences greater than Last-Event-ID; an omitted cursor starts at zero, and `?after=5` is an alternative. Header and query cursors must agree. Terminal Runs close after replay; a cursor at the end yields only a connected comment. Legacy terminal Runs without events return empty history. Browser EventSource clients should close on a terminal event to avoid reconnecting an ended stream. curl requires manual reconnection and cursor tracking.

Active streams poll PostgreSQL every0.5 seconds with100-event pages and15-second heartbeats. Each read uses a short Session, released before network delivery or waiting. History and live events use one database cursor without a subscription handoff gap. There are16 observation slots per process, separate from diagnosis execution slots; overload returns429 REPLAY_BUSY. Disconnect releases the slot without cancelling the Run. Disabled persistence returns503, missing Runs404, malformed or conflicting cursors422, future cursors409 INVALID_EVENT_CURSOR, and sequence gaps409 EVENT_HISTORY_GAP. Errors after streaming starts use stream_failed without an SSE ID.

No retention or410 expiry policy is implemented. Clients must still deduplicate event IDs. Orphaned running Runs will wait and emit heartbeats until restart recovery is implemented; use curl `--max-time` to bound a manual observation.

The API defaults to a 180-second shared execution budget (`EVIDENCEOPS_RUN_TIMEOUT_SECONDS`). Each model/tool wait uses the smaller of its own timeout and the remaining budget. Budget exhaustion produces `RUN_TIMEOUT`; earlier individual timeouts retain `MODEL_TIMEOUT` or `TOOL_TIMEOUT`. Restart the API after changing environment variables. The example sets individual model timeout to 120 seconds; its default remains 60 seconds.

This is not a hard response deadline. The API's real Provider now uses request-local async HTTP tasks, checking cancellation and the Run budget approximately every 50 ms and awaiting local IO cleanup. Synchronous third-party Providers still require return-time checks. Database commits and cleanup can exceed the budget; running tool threads cannot be forcibly stopped. The budget starts inside DiagnosisService, excluding earlier HTTP parsing/admission. See `tests/test_run_budget.py` for deterministic failure checks.

## Explicit cancellation (single process)

Restart the API, start a streaming diagnosis, and copy its Run ID from `run_started`. In another PowerShell window:

```powershell
$run_id=(Read-Host "Paste the active run_id").Trim()
curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/agent/runs/$run_id/cancel"
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/$run_id"
```

202 accepts the cancellation request; it does not confirm durable cancellation. Repeated requests are idempotent. SSE emits `run_cancel_requested`, then `run_cancelled` after persistence. Final history has `status=cancelled`, `error_code=null`, and `report=null`, retaining validated Evidence and execution records. Cancelled call records use `status=cancelled / error_code=RUN_CANCELLED`; the Run domain treats cancellation as a separate terminal state rather than failure.

Once finalization is claimed, cancellation returns409 with `phase=finalizing`; the target status is not a commit confirmation. Persisted terminal Runs return200 without changing state. Unknown IDs return404. A persisted running Run absent from this process returns409 `RUN_NOT_ACTIVE`. Memory mode cannot look up completed Runs, so a subsequent cancellation may return404.

Each Run has a separate Event and terminal-decision lock. Model cancellation cleans up local IO; it does not guarantee remote generation or billing stops. The three local JSONL Connectors check cancellation per row and close their files. Other tools may supply `controlled_handler(arguments,control)` using `control.check()` and `control.wait(seconds)`. Non-cooperative running threads may retain handler-pool slots; late results cannot create a successful report. A cancelled Run does not prove every thread has stopped.

The registry is process-local: use one worker. Cross-worker/host cancellation, durable cancellation requests, and restart recovery are not implemented. Request-local AsyncClient/event-loop ownership preserves the synchronous orchestration interface at the cost of cross-round HTTP connection reuse. An explicitly injected synchronous client without an async_client_factory is preserved; its IO can only be checked before/after the call. Run deterministic cancellation checks without model charges:

```powershell
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_run_cancellation.py -q -p no:cacheprovider
```

Coverage includes API/SSE and SQLAlchemy+SQLite history, Run isolation, terminal races, real localhost TCP read cancellation, queued tools, cooperative/non-cooperative handlers, and Connector file closure. Real-provider/PostgreSQL cancellation acceptance remains a separate manual check.

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

## Roadmap

- [x] Agent Loop, Tool Runtime, Evidence validation, and structured reports.
- [x] Real OpenAI-compatible model path with bounded multi-tool execution.
- [x] PostgreSQL persistence for Runs, Evidence, reports, and execution records.
- [x] SSE lifecycle events, shared budgets, timeout handling, and single-process cancellation.
- [x] 20-case offline Eval and CLI semantic review.
- [x] Persist business events and commit terminal events atomically with Run results.
- [x] Paginated event history and `Last-Event-ID` replay after disconnects.
- [ ] Recover active or incomplete Runs after service restart.
- [ ] Learn and implement a minimal RAG pipeline with document ingestion, hybrid retrieval, and Evidence citations.
- [ ] Add language and framework adapters for Python, Java, Go, JavaScript/TypeScript, and C/C++.
- [ ] Add Rust, PHP, and C# adapters after the first batch is evaluated.
- [ ] Add LangChain and LangGraph comparison adapters without replacing the self-built core.
- [ ] Add MCP, OpenTelemetry, cross-worker coordination, and production security controls.

## Contributing

The project is developed in small, testable slices. A change should define its boundary, implement deterministic normal and failure paths, add focused tests, and update the relevant documentation. Keep secrets and generated evaluation artifacts out of Git.

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

## Acknowledgments

- [Best-README-Template](https://github.com/othneildrew/Best-README-Template) for the README organization reference.
- FastAPI, PostgreSQL, SQLAlchemy, Alembic, pytest, and the OpenAI-compatible ecosystem.
