# Spec Validation Evaluation Summary

- Run timestamp (UTC): `20260217_cons3_expanded_all_modes_merged`
- Cases file: `artifacts\validation_benchmark\cases.expanded.jsonl`
- Modes: `deterministic, llm, hybrid`

| Mode | Cases | Labeled | Accuracy | Precision (fail) | Recall (fail) | Stability | Reason Recall | Reason Prec | Over-flag % | Avg Latency ms | Median Latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deterministic | 72 | 72 | 70.8% [70.7%, 71.4%] | 96.2% [96.1%, 96.6%] | 55.6% [55.5%, 56.4%] | 100.0% | 55.6% | 96.2% | 0.0% | 19.97 | 14.47 |
| llm | 72 | 72 | 75.0% [74.8%, 75.4%] | 88.6% [88.4%, 89.0%] | 68.9% [68.6%, 69.4%] | 96.8% | 64.4% | 55.7% | 0.0% | 17204.23 | 16740.52 |
| hybrid | 72 | 72 | 79.2% [78.8%, 79.4%] | 91.7% [91.5%, 92.0%] | 73.3% [72.9%, 73.7%] | 97.2% | 68.9% | 58.3% | 0.0% | 17595.94 | 17280.89 |

## Clean Metrics (provider errors excluded)

| Mode | Provider Errors | Clean Cases | Clean Accuracy | Clean Precision (fail) | Clean Recall (fail) | Clean F1 (fail) |
|---|---:|---:|---:|---:|---:|---:|
| deterministic | 0 | 72 | 70.8% | 96.2% | 55.6% | 70.4% |
| llm | 0 | 72 | 75.0% | 88.6% | 68.9% | 77.5% |
| hybrid | 0 | 72 | 79.2% | 91.7% | 73.3% | 81.5% |

## Disagreements
- `deterministic_vs_llm`: 9 case(s)
  - Sample: p10-base, p10-syn-0, p10-syn-3, p7-s37-v8, p7-s58-v8, p7-syn-14, p7-syn-3, p9-syn-2, p9-syn-3
- `deterministic_vs_hybrid`: 10 case(s)
  - Sample: p10-base, p10-syn-0, p10-syn-3, p7-s58-v8, p7-syn-14, p7-syn-3, p9-syn-0, p9-syn-1, p9-syn-2, p9-syn-3
- `llm_vs_hybrid`: 3 case(s)
  - Sample: p7-s37-v8, p9-syn-0, p9-syn-1
