# Contributing to EvidenceOps

Thanks for your interest in contributing. This document covers the development setup, the commands used to verify changes, and what a good pull request looks like.

## Development setup

| Component | Version |
| --- | --- |
| Python | 3.14 |
| Node.js | 20.9 or later |
| C++ compiler | C++20 capable (MSVC/Clang/GCC), CMake 3.20+ |
| Shell | PowerShell 7 (`pwsh`) |

```powershell
# Backend dependencies
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt

# Frontend dependencies and build
cd frontend
npm ci
npm run build
```

Copy `.env.example` to `.env` if you need PostgreSQL or a real model connection. A fresh installation runs on SQLite with the deterministic Mock provider and requires no credentials.

## Running the application

```powershell
# Complete application (web console on 3013, API on 8014)
pwsh -File scripts/start_installed.ps1

# Development API only (no web console, memory persistence)
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
$env:EVIDENCEOPS_PROVIDER='mock'
$env:EVIDENCEOPS_PERSISTENCE='memory'
.\.venv\Scripts\python.exe -m uvicorn evidenceops.api.agent_app:app --host 127.0.0.1 --port 8000
```

## Tests

```powershell
# Backend regression suite
$env:PYTHONPATH=(Join-Path $PWD.Path 'src')
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider

# C++ log parser (independent build)
cd cpp/log_evidence_engine
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure

# Frontend
cd frontend
npm test
npm run typecheck
npm run build
```

PostgreSQL-backed tests are opt-in: set `EVIDENCEOPS_TEST_POSTGRES='1'` plus the `POSTGRES_*` variables, run pytest, then unset them.

The 20-case diagnosis evaluation suite can be run offline:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation --mode mock --output eval_result_mock.json
```

## Pull-request checklist

- [ ] Domain rules stay separate from model/database adapters and frontend transport.
- [ ] Failure-path tests are included for the changed behavior.
- [ ] Both `README.md` and `README.zh-CN.md` are updated when API or configuration documentation changes.
- [ ] No credentials, local databases, or generated evaluation artifacts are committed.
- [ ] Python dependency changes go through `requirements.txt` / `requirements-dev.txt`; frontend changes go through `package-lock.json`.
- [ ] The "What it does not do" section of the READMEs still holds — if a change extends the operating scope, call it out explicitly in the PR description.

## Code of conduct

By participating you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting security issues

Please do not open public issues for suspected vulnerabilities. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
