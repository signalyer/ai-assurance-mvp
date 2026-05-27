# SESSION-58 — Azure Architect eval calibration + portal visibility

**Status entering S58:** S57a shipped the offline P6 eval runner at
`agents/azure-architect/eval/run_eval.py`. It scores candidate output JSONL
against the 5-row manifest dataset and persists run summaries to
`data/azure_architect_eval_runs.jsonl`. No live candidate outputs have been
generated yet because P4 synthesis/orchestration remains skeletal.
S57b also grouped the Team Portal `/evals` detail view into suite bands with
individual test rows, but it still reads simulated GRC eval data rather than
`data/azure_architect_eval_runs.jsonl`.

## Objectives

1. Generate real candidate outputs for all 5 dataset rows.
2. Run the offline eval suite without monkeypatching `mermaid_compiles`.
3. Wire Azure architect eval run history into the grouped Team Portal eval
   view or a small engine read endpoint.
4. Decide whether P6 can close or remains blocked by P4 agent core.

## Steps

### Step 1 — Mermaid CLI readiness

Install or locate `mmdc` for local compile checks:

```
npm install -g @mermaid-js/mermaid-cli
mmdc --version
```

If global install is not allowed, document the blocker and use a repo-local
Node tool path. Do not route diagrams to Kroki unless explicitly approved.

### Step 2 — Candidate output generation

Use the P4 synthesis path once implemented, or a temporary internal runner that
calls the same synthesis function the agent will use in production. Output file
shape:

```
{"id":"simple-1rg","actual_output":"{\"mermaid_source\":\"graph TD...\",\"manifest\":[...]}"}
```

Save candidate JSONL outside source-controlled paths unless the examples are
explicitly scrubbed and approved for commit.

### Step 3 — Run and inspect evals

Run:

```
python agents/azure-architect/eval/run_eval.py --outputs <candidate-output.jsonl>
python agents/azure-architect/eval/run_eval.py --list-runs --limit 5
```

Acceptance: at least 4/5 cases pass; failing cases have clear metric-level
reasons.

### Step 4 — Portal/API visibility for real runs

Add a read endpoint or extend the existing evals endpoint so operators can see
Azure architect run history without reading JSONL manually. Keep it read-only
and reuse the grouped Team Portal eval bands rather than adding a separate
flat list.

Acceptance: Team Portal or API can list latest Azure architect eval runs with
run id, timestamp, pass count, overall score, and per-case failures.

## Open questions

- Should Azure architect evals be stored in the generic `data/evals.jsonl`
  contract as well as `data/azure_architect_eval_runs.jsonl`, or is the
  workload-specific run file the right source for this P6 artifact?
- Does the Team Portal eval card need to distinguish simulated GRC evals from
  real workload evals before P6 can close?
- Should `mermaid_compiles` be treated as blocking when `mmdc` is missing, or
  should the runner support an explicit `--skip-compile` for CI-only smoke?

## Exit gate

P6 can close only when the eval runner scores real Azure architect output,
persists the run, and exposes the run history through an operator-facing
surface. Until then, S57a is a harness milestone, not the full P6 exit gate.
