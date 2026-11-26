# Human Semantic Review v1

## Scope

This workflow keeps report semantics separate from automatic tool-contract checks, retrieval measurements, and model usage. It does not use an LLM judge or a frontend review page.

Cases without a report remain in the execution evaluation and are excluded from claim-quality denominators. Cases with a report are reviewed at the root-cause and recommendation level. A report can have one review per claim and a separate case-level completeness and answerability assessment.

## Freeze A Real Batch

Run the freeze command against the exact result JSON and case file used by the evaluation. The command creates a new file and refuses to overwrite an existing result.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review-freeze `
  eval_real_20261125_b0db1e50.json `
  --cases samples/evaluation/cases.json `
  --references samples/evaluation/semantic_references.json `
  --output eval_semantic_baseline_20261125.json
```

The frozen artifact binds the source result hash, case file, reference standard file, Run IDs, model configuration fingerprints, prompt template fingerprint, fixture hashes, and evidence snapshot. Historical results that did not retain the actual model request are marked with unknown visibility. A current prompt-source fingerprint does not prove which prompt a past Run received.

The selected 20-case real result has 7 report-bearing Runs and 13 Runs without reports. The latter remain execution-only. Its historical model requests were not captured, so cited Evidence visibility is unknown and the batch is marked not ready for prompt-effect comparison. A separate real Python RAG result is frozen as its own batch. Neither batch contains human judgments yet, so semantic rates remain null until reviewers annotate them.

## Independent Reviews

Each reviewer uses a distinct identifier. The interactive command displays the case standard, each report claim, cited Evidence bodies and source identity, and whether each Evidence was visible in the final captured model request. If the model received a clipped or otherwise different body, the actual request snapshot and the full collected body are shown separately. It does not display the generation model name or batch experiment label.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review `
  eval_semantic_baseline_20261125.json --reviewer reviewer-a
```

Run the same command with a second reviewer identifier for independent calibration. Results are marked as single-review, consensus, disputed, or adjudicated. Disputed cases are omitted from quality-rate numerators and denominators until adjudicated.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review `
  eval_semantic_baseline_20261125.json --reviewer reviewer-b
```

When independent reviews disagree, a reviewer with adjudicator role records the resolution.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review `
  eval_semantic_baseline_20261125.json --reviewer reviewer-lead --role adjudicator
```

The JSON workflow supports exporting an empty template, completing it externally, and importing the complete review after validation.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review-template `
  eval_semantic_baseline_20261125.json --reviewer reviewer-a --output review-a.json
.\.venv\Scripts\python.exe -X utf8 -m evidenceops.evaluation review-import `
  eval_semantic_baseline_20261125.json review-a.json
```

Import validates the batch fingerprints, case and Run identities, exact report claim text, every claim citation, Evidence ownership, Evidence content hash, model-visibility label, reference-fact coverage, reason fields, and reviewer identity before writing any review.

## Metrics

The result keeps automatic `rule_pass_rate` and `semantic_quality` separate. Semantic quality reports supported-root-cause rate, unsupported-root-cause rate, recommendation support rate, required-fact coverage, correct refusal rate for insufficient-evidence cases, pending and disputed cases, single-review cases, adjudications, and inter-rater agreement. A single reviewer is explicitly reported as single-review and does not produce an agreement score.

The current fixed sample set has no contradictory observed-evidence case. This gap is listed in the reference standards instead of being represented by a synthetic conflict result.
