# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-23

### Added

- Initial public release of the EvidenceOps workbench.
- Provider-independent Agent Loop with an OpenAI-compatible adapter and a deterministic Mock provider.
- Bounded, read-only tool execution: allowlisted registration, argument validation, call correlation, and cooperative cancellation.
- Evidence-backed reports: source, observation time, location, version, content hash, Run-scoped reference checks, and archived snapshots.
- C++20 log parser CLI with a Python adapter for bounded, validated log evidence (glog, ZooKeeper, muduo, plain-text formats).
- Web console (Next.js): diagnosis workspace, searchable Run history, evidence drawer, execution timeline, offline evaluation viewer, model connection management, and storage maintenance.
- Streaming and replay: SSE lifecycle events with cursor-based replay; persisted Run history on SQLite or PostgreSQL.
- Context governance: per-request token estimation, output/safety reservations, per-Run token budget, provider usage records.
- Offline evaluation: 20-case diagnosis suite with automated rules and resumable CLI human review.
- Knowledge retrieval: document versions, chunk sets, embedding sets, exact cosine search, keyword/BM25 baselines, and RRF fusion comparisons with fragment-level Precision/Recall/MRR evaluation.

[0.1.0]: https://github.com/Rrrayy/EvidenceOps/releases/tag/v0.1.0
