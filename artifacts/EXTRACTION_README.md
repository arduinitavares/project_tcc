# TCC Metrics Extraction - Provenance Documentation

This directory contains extracted evaluation metrics for Chapter 6 (Resultados) of the thesis.

## Data Sources

### Production Database: `db/spec_authority_dev.db` ⭐ (ACTIVE)
- **Location:** `<project_root>/db/spec_authority_dev.db`
- **Configured via:** `.env` → `PROJECT_TCC_DB_URL=sqlite:///./db/spec_authority_dev.db`
- **Size:** ~260 KB
- **Last Modified:** 2026-02-01
- **Contains:** 2 products with spec authority validation, 7 stories (4 with validation_evidence)
- **Schema Version:** Full spec authority schema (includes spec_registry, compiled_spec_authority, spec_authority_acceptance)
- **Projects:**
   1. Review-First Human-in-the-Loop Extraction Pipeline (2 stories)
   2. HashbrownVision Phase 1 (5 stories, 1 sprint)

### ADK Session Database: `agile_sqlmodel.db`
- **Location:** `<project_root>/agile_sqlmodel.db`
- **Size:** ~52 KB (session storage only)
- **Contains:** Google ADK session data (app_states, events, sessions, user_states)
- **Note:** NOT used for evaluation metrics; contains conversation history only

### Smoke Run Logs: `artifacts/smoke_runs.jsonl`
- **Location:** `<project_root>/artifacts/smoke_runs.jsonl`
- **Format:** JSON Lines (one run per line)
- **Contains:** 24 automated pipeline runs with timing metrics, validation results, alignment checks

## Extracted Files

### `metrics_summary.csv`
Main metrics summary in CSV format, containing:
- Extraction metadata (timestamp, DB path, commit hash)
- Per-product metrics (story counts, sprint counts, spec pinning coverage)
- Workflow events summary

### `metrics_summary.json`
Complete extraction result in JSON format, including:
- Full schema information for all tables
- Detailed per-product metrics
- Smoke run aggregated metrics
- Task-to-event mapping documentation

### `query_results/`
Individual CSV files for each metric category:
- `products_metrics.csv` - Per-product aggregated metrics
- `workflow_events_summary.csv` - Event type counts and timing
- `smoke_runs_metrics.csv` - Smoke test pipeline metrics

### `sql_queries/`
SQL query files that reproduce each metric:
- `01_products_summary.sql` - Product overview
- `02_stories_per_product.sql` - Story counts with spec pinning
- `03_sprints_summary.sql` - Sprint data with linked stories
- `04_workflow_events_timing.sql` - Full event log
- `05_sprint_plan_cycle_time.sql` - T5 cycle time extraction
- `06_spec_authority_status.sql` - Spec registry state
- `07_spec_authority_acceptance.sql` - Acceptance decisions
- `08_validation_evidence_details.sql` - Story validation results
- `09_story_approval_rates.sql` - Approval rate calculation
- `10_sprint_capacity_check.sql` - Capacity verification

## Extraction Methodology

### Task-to-Event Mapping (T1-T5)

| Task | Description | DB Representation | Timing Source |
|------|-------------|-------------------|---------------|
| T1 | Definição de Visão | `products.vision` | [PLACEHOLDER: external] |
| T2 | Especificação Técnica | `spec_registry.created_at` | [PLACEHOLDER: external] |
| T3 | Compilação de Autoridade | `compiled_spec_authority.compiled_at` | Timestamp delta |
| T4 | Geração de Backlog | `user_stories.created_at` | Aggregate by product |
| T5 | Planejamento de Sprint | `WorkflowEvent.duration_seconds` | **Explicit in DB** |

**Important Notes:**
- Only T5 (Sprint Planning) has explicit duration tracking via `WorkflowEvent.SPRINT_PLAN_SAVED.duration_seconds`
- T1-T4 timings must be computed from timestamp differences or collected externally
- Baseline manual times are NOT stored in the database
- NASA-TLX scores are NOT stored in the database

### Data NOT in Database

The following evaluation data was collected externally and must be included manually in Chapter 6:

1. **Baseline (Manual) Cycle Times:**
   - T1: 18 minutes
   - T2: 25 minutes
   - T4: 42 minutes
   - T5: 22 minutes

2. **NASA-TLX Scores:**
   - Baseline: Mental=75, Temporal=80, Effort=70, Frustration=60, Performance=40 (Mean: 65)
   - Experimental: Mental=45, Temporal=40, Effort=35, Frustration=25, Performance=20 (Mean: 33)

## How to Re-Extract

```bash
# From project root
cd c:\Users\mjnrc\projects\project_tcc

# Extract from PRODUCTION database (configured in .env)
python scripts/extract_tcc_metrics.py db/spec_authority_dev.db

# Run individual SQL queries
# (Requires sqlite3 CLI or DB browser)
sqlite3 db/spec_authority_dev.db < artifacts/sql_queries/05_sprint_plan_cycle_time.sql
```

## Reproducibility

- All extractions are deterministic (same DB → same outputs)
- Commit hash at extraction time is recorded in outputs
- SQL queries are parameterless and can be re-run independently

## Known Limitations

1. **Database Configuration:** The active database is configured via `.env` file (`PROJECT_TCC_DB_URL`). Currently set to `db/spec_authority_dev.db`.
2. **Limited Data:** Only 2 projects and 7 stories in the active database; this is a development/evaluation dataset
3. **Validation Evidence:** Available for 4 of 7 stories (57.1% coverage)
4. **Timing Granularity:** Only `SPRINT_PLAN_SAVED` events have explicit `duration_seconds`; other timing requires timestamp math
5. **Baseline Data:** Manual scenario data is not in any database; must be maintained separately

## Last Extraction

- **Timestamp:** [Set by extraction script]
- **Git Commit:** [Set by extraction script]
- **Extracted By:** `scripts/extract_tcc_metrics.py`
