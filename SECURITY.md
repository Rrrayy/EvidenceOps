# Security Policy

## Supported versions

This project is in early development and distributed from source only. Security fixes are applied to the latest commit on the default branch.

| Version | Supported |
| --- | --- |
| latest `main` | ✅ |
| older commits / forks | ❌ |

## Reporting a vulnerability

**Do not open a public GitHub issue for suspected security problems.**

Use GitHub's [Private Vulnerability Reporting](../../security/advisories/new) for this repository. Include:

1. The affected component (API, web console, storage layer, C++ parser, launcher scripts).
2. Reproduction steps and, if possible, a minimal proof of concept.
3. Your assessment of severity and impact.

You will receive an acknowledgement within 7 days. If the report is confirmed, a fix will be developed privately and released with credit to the reporter (unless anonymity is requested).

## Scope notes

This application targets a **local, single-tenant deployment** with one API worker:

- There is no remote identity, multi-user authorization, or distributed coordination. Running the service on a network-reachable interface is outside the supported deployment scope.
- Model credentials are stored encrypted at rest; keys are never returned by read APIs and never enter browser persistent storage, URLs, or logs.
- Citation checks verify evidence identity and ownership. They do **not** establish semantic correctness, and prompt-injection boundaries in prompts do not guarantee full mitigation.
- The C++ log parser processes operator-registered files with bounded resources; it is not hardened against adversarially crafted binary inputs beyond the formats documented in the README.
