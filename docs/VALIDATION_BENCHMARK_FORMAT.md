# Validation Benchmark Format

This document defines the benchmark dataset and evaluation workflow for comparing story validation modes:

- `deterministic`
- `llm`
- `hybrid`

## Dataset File

Default path:

- `artifacts/validation_benchmark/cases.jsonl`

Each line is one JSON object (one benchmark case).

## Case Schema

Required fields:

- `case_id` (string): Stable identifier for tracking a case across runs.
- `story_id` (int): Story to validate.
- `spec_version_id` (int): Spec authority version pinned for this case.

Recommended labeling fields:

- `expected_pass` (bool or null): Human-labeled expected verdict.
- `expected_fail_reasons` (array of strings): Expected failure codes/rules.
- `notes` (string or null): Reviewer notes.
- `tags` (array of strings): Optional grouping tags (for reporting slices).
- `enabled` (bool): If `false`, evaluator skips the case.

Optional context fields (ignored by evaluator metrics):

- `product_id` (int)
- `story_title` (string)
- `label_source` (string)

## Example Case

```json
{
  "case_id": "p8-s75-v9",
  "story_id": 75,
  "spec_version_id": 9,
  "expected_pass": false,
  "expected_fail_reasons": ["FORBIDDEN_CAPABILITY", "RULE_LLM_SPEC_VALIDATION"],
  "notes": "Story mentions forbidden cloud dashboard capability.",
  "tags": ["forbidden-capability", "real-data"],
  "enabled": true
}
```

## Workflow

1. Build initial candidate cases from real DB data:
`python scripts/build_validation_benchmark_cases.py --output artifacts/validation_benchmark/cases.jsonl`
2. Export reviewer sheet (strips direct benchmark labels and adds context):
`python scripts/export_benchmark_for_labeling.py --cases artifacts/validation_benchmark/cases.jsonl --output artifacts/validation_benchmark/cases_for_labeling.jsonl`
3. Human reviewer fills `rater_*` fields in JSONL (one JSON object per line).
4. Import human labels:
`python scripts/import_human_labels.py --cases artifacts/validation_benchmark/cases.jsonl --labels artifacts/validation_benchmark/cases_for_labeling.jsonl --output artifacts/validation_benchmark/cases.human_review.jsonl`
5. Run evaluator:
`python scripts/eval_spec_validation.py --cases artifacts/validation_benchmark/cases.jsonl --modes all`
6. Inspect outputs in `artifacts/validation_eval/`.

## Output Artifacts

Per run, evaluator writes:

- Raw results JSONL:
`artifacts/validation_eval/raw_<timestamp>.jsonl`
- Aggregate metrics JSON:
`artifacts/validation_eval/results_<timestamp>.json`
- Human-readable summary:
`artifacts/validation_eval/summary_<timestamp>.md`

## Labeling Guidance

1. Use human judgment as source of truth, not existing validator output.
2. Mark ambiguous cases in `notes`.
3. Keep `case_id` stable once published.
4. Prefer real project cases first; add synthetic edge cases only when needed.
5. After importing labels, prefer running evaluator on `cases.human_review.jsonl`.
