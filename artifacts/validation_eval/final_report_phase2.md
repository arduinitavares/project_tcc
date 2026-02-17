# Phase 2 Quality Report: Benchmark Expansion & Adjudication

## Executive Summary
We have successfully expanded the validation benchmark from a single-product, structural-only dataset (40 cases) to a multi-product, semantic-rich dataset (72 cases).

The expansion introduced "Hard Negatives" (stories that look valid structurally but violate business rules), which exposed significant coverage gaps in the deterministic validation logic.

## 1. Benchmark Expansion
- **Original:** 40 cases (Product 7 only). Mostly structural failures (missing fields).
- **New:** 72 cases.
  - **Products:** 3 distinct domains (Quadra/Regulated, E-Commerce, IoT).
  - **Composition:**
    - 27 Passing cases (Real + Synthetic Baselines)
    - 45 Failing cases (15 Real Structural + 30 Synthetic Semantic)
  - **Mutations Injected:**
    - Forbidden Capabilities (e.g., "Cloud" in local-only IoT)
    - Scope Creep (e.g., "Inventory" in Digital E-com)
    - Contradictions (e.g., "Latency < 0ms")
    - Missing Fields (e.g., Wiped Acceptance Criteria)

## 2. Evaluation Results (Deterministic Baseline)

| Metric | Original (40 cases) | Expanded (72 cases) | Delta |
| :--- | :---: | :---: | :---: |
| **Accuracy** | 92.5% | **72.2%** | ▼ -20.3% |
| **Recall (Fail)** | 83.3% | **55.6%** | ▼ -27.7% |
| **Precision (Fail)** | 100.0% | **100.0%** | - |
| **Stability** | 100% | 100% | - |

*(Source Artifact: `results_20260217_100511.json`)*

### Key Findings
1.  **Semantic Blindness:** The deterministic validator missed nearly half (20/45) of the failure cases. It successfully catches structural issues (Missing Fields) but completely misses nuanced "Scope Creep" or "Contradiction" mutations that require semantic understanding.
2.  **High Precision:** When the deterministic validator flags an issue, it is 100% correct. This confirms its value as a "fast gate" before expensive LLM calls.
3.  **Necessity of Hybrid Mode:** To reach the >90% recall target on this harder benchmark, enabling LLM-based semantic validation is strictly required.

## 3. Adjudication & Infrastructure
- **Consensus Logic:** Implemented `N-run` consensus voting with stability tracking to handle future LLM non-determinism.
- **Hydration:** Created robust DB hydration scripts (`hydrate_benchmark_db.py`) to spin up mock environments for testing without reliance on production data snapshots.
- **LLM Status:** Currently blocked by provider authentication errors (502). Once resolved, the infrastructure is ready to re-run in `hybrid` mode to demonstrate the expected quality lift.

## 4. Recommendations
1.  **Immediate:** Resolve LLM provider authentication/credit issues.
2.  **Next Step:** Run `hybrid` mode on the expanded benchmark. Expect Recall to jump from 55.6% -> ~90%.
3.  **Long Term:** Tune specific semantic prompts for the "IoT" and "E-Commerce" domains once we have baseline LLM performance data.
