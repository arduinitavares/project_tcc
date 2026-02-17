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
| **Accuracy** | 92.5% | **61.1%** | ▼ -31.4% |
| **Recall (Fail)** | 83.3% | **40.0%** | ▼ -43.3% |
| **Precision (Fail)** | 100.0% | **94.7%** | ▼ -5.3% |
| **Stability** | 100% | 100% | - |

### Key Findings
1.  **Semantic Blindness:** The deterministic validator failed to catch ~60% of the new failure cases. It cannot detect "Scope Creep" or subtle "Forbidden Capabilities" that don't match exact keyword strings.
2.  **High Precision:** When the deterministic validator *does* flag an issue (mostly structural), it is almost always correct (94.7%).
3.  **Necessity of Hybrid Mode:** To reach the >90% recall target on this harder benchmark, enabling LLM-based semantic validation is strictly required. The current deterministic logic is insufficient for product quality goals.

## 3. Adjudication & Infrastructure
- **Consensus Logic:** Implemented `N-run` consensus voting with stability tracking.
- **Hydration:** Created robust DB hydration scripts (`hydrate_benchmark_db.py`) to spin up mock environments for testing without reliance on production data snapshots.
- **LLM Status:** Currently blocked by provider authentication errors (502). Once resolved, the infrastructure is ready to re-run in `hybrid` mode to demonstrate the expected quality lift.

## 4. Recommendations
1.  **Immediate:** Resolve LLM provider authentication/credit issues.
2.  **Next Step:** Run `hybrid` mode on the expanded benchmark. Expect Recall to jump from 40% -> ~90%.
3.  **Long Term:** Tune specific semantic prompts for the "IoT" and "E-Commerce" domains once we have baseline LLM performance data.
