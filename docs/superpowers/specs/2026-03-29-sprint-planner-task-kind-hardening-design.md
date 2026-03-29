# Sprint Planner Task Kind Hardening Design

**Date:** 2026-03-29
**Status:** Approved for planning
**Scope:** Sprint planner prompt contract, schema-boundary compatibility normalization, and sprint failure reporting

## Summary

Sprint generation is currently too brittle at the boundary between planner output and runtime validation. Two recent failures show the problem:

- the planner emitted `task_kind: "review"`, which is not a supported literal in the sprint output schema
- a separate sprint run reached deterministic decomposition validation and failed for poor task decomposition quality

These are related but different issues. The first is harmless schema or prompt drift. The second is a real planning-quality failure that should remain strict.

This design hardens the sprint planner contract without weakening structural quality gates:

- tighten the planner prompt so it emits only canonical sprint task kinds and clearer task decomposition
- add bounded deterministic normalization for `task_kind` at the shared schema boundary
- keep structural decomposition validation strict
- improve failed sprint responses so users see compact retry guidance while full failure artifacts remain available for debugging

## Problem Statement

The current sprint planner stack has a contract gap between what the model may emit and what the platform accepts.

The planner agent in [`orchestrator_agent/agent_tools/sprint_planner_tool/agent.py`](../../../orchestrator_agent/agent_tools/sprint_planner_tool/agent.py) declares `output_schema=SprintPlannerOutput`, so some invalid outputs can fail inside the ADK runner before the sprint runtime gets a chance to apply any post-processing. The runtime in [`services/sprint_runtime.py`](../../../services/sprint_runtime.py) also performs its own `SprintPlannerOutput.model_validate(...)`, which means output validation happens at multiple boundaries.

Because structured task validation is defined through [`StructuredTaskSpec`](../../../utils/task_metadata.py), any compatibility behavior that is intended to protect both boundaries must be anchored there, not only in the runtime.

At the same time, the platform already contains deterministic decomposition-quality checks in [`validate_task_decomposition_quality(...)`](../../../orchestrator_agent/agent_tools/sprint_planner_tool/schemes.py). Those checks correctly reject weak checklist scoping, duplicate tasks, missing tags, and file-path artifact targets. They should not be relaxed in the name of resilience.

The system therefore needs a narrow compatibility layer for enum-like drift, while preserving loud failure for genuine planning-quality defects.

## Goals

- Prevent harmless `task_kind` surface drift from failing the entire sprint run.
- Keep sprint task kinds within the existing canonical taxonomy.
- Ensure compatibility behavior applies at the earliest shared schema boundary.
- Make the planner prompt more explicit about allowed task kinds and decomposition expectations.
- Preserve strict deterministic failure for structural decomposition-quality issues.
- Surface compact structured retry guidance on failed sprint responses and sprint history.

## Non-Goals

- Adding new public task kinds such as `review`.
- Expanding persisted task metadata beyond the current task-kind taxonomy.
- Auto-repairing weak decomposition, missing checklist items, duplicate tasks, or bad artifact targets.
- Softening or bypassing `validate_task_decomposition_quality(...)`.
- Introducing semantic inference for ambiguous planner output beyond a tiny allowlisted synonym set.

## Design Principles

### 1. Normalize Only Surface Drift

Compatibility behavior should correct only deterministic surface mismatches such as casing, whitespace, and a tiny set of observed task-kind synonyms.

### 2. Keep Structural Quality Strict

If the planner emits poor task decomposition, the run should still fail. Resilience must not hide quality problems that require prompt correction or retry.

### 3. Normalize at the Shared Boundary

Because both the ADK output-schema path and the runtime validation path rely on the same task model, canonicalization should live at the `StructuredTaskSpec` and `TaskMetadata` boundary in [`utils/task_metadata.py`](../../../utils/task_metadata.py).

### 4. Explain Failures Actionably

Top-level sprint failures should remain concise, but the returned failure payload should include enough structured detail for the UI to render a short "what to fix" list.

## Architecture

The hardened contract has four layers.

### Preventive Layer: Planner Prompt

[`orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt`](../../../orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt) becomes more explicit about both task-kind selection and decomposition-quality expectations.

The prompt should distinguish between:

- the schema literal set: `analysis`, `design`, `implementation`, `testing`, `documentation`, `refactor`, `other`
- the planner's normal emission contract: `analysis`, `design`, `implementation`, `testing`, `documentation`, `refactor`

The prompt should explicitly tell the planner not to emit `other` for normal sprint output, because deterministic validation rejects it for sprint tasks.

It should also show review-like work as canonical output, for example:

- final verification of a task -> `testing`
- writing architecture notes -> `documentation`
- inspecting current subsystem boundaries -> `analysis`

For decomposition quality, the prompt should add both positive and negative guidance:

- do not restate story acceptance criteria as task checklist items
- do not emit duplicate or near-duplicate sibling tasks
- do not use file paths or glob-like targets in `artifact_targets`
- do provide short task-local checklist items and component-level artifact targets

### Compatibility Layer: Shared Task Kind Canonicalization

Bounded normalization should live in a small shared helper inside [`utils/task_metadata.py`](../../../utils/task_metadata.py).

That helper should:

- trim surrounding whitespace
- normalize casing for canonical values and allowlisted synonyms
- map a tiny synonym table to canonical task kinds

Initial synonym table:

- `review` -> `testing`
- `qa` -> `testing`
- `validation` -> `testing`

This helper should be used by both:

- `StructuredTaskSpec.task_kind`
- `TaskMetadata.task_kind`

This keeps canonical task-kind handling consistent across agent output validation and persisted metadata handling.

Unknown values such as `approval` must still fail validation. The helper must not guess broader meanings such as `planning` or `finalization` unless future evidence justifies extending the allowlist.

### Enforcement Layer: Strict Schema and Quality Gates

[`SprintPlannerOutput`](../../../orchestrator_agent/agent_tools/sprint_planner_tool/schemes.py) and [`StructuredTaskSpec`](../../../utils/task_metadata.py) remain the authoritative schema contract.

`validate_task_decomposition_quality(...)` must stay strict and continue rejecting structural problems including:

- `task_kind="other"`
- missing `artifact_targets`
- missing `workstream_tags`
- empty `checklist_items`
- duplicate task descriptions
- file-path-like `artifact_targets`
- checklist items that duplicate or restate story-level acceptance criteria

This layer is intentionally not repaired automatically.

### Runtime and UI Layer: Better Retry Guidance

[`services/sprint_runtime.py`](../../../services/sprint_runtime.py) should continue to fail sprint generation when validation fails, but it should package clearer structured retry hints.

For failed sprint responses and sprint history, the public wire shape of `validation_errors` should be pinned as `list[str]`. Those strings should be short user-facing retry hints, not raw Pydantic error dictionaries. Full structured validation details should stay in the persisted failure artifact for debugging.

For task-kind validation failures, the returned failure payload should include:

- the invalid emitted value when available from validation details
- the allowed canonical set
- a compact suggestion to use one of the supported kinds

For decomposition-quality failures, the top-level error should remain strict, but `validation_errors` should contain a compact list of the first actionable causes, such as:

- task checklist restates story acceptance criteria
- duplicate sibling tasks detected
- artifact target looks like a file path

The failed sprint response and any sprint-history surface derived from it should expose those compact `validation_errors: list[str]`, while the full failure artifact continues to preserve raw exception and validation context for debugging.

The sprint setup UI should also make the retry path clearer. The current `Planning Notes` input in [`frontend/project.html`](../../../frontend/project.html) should be renamed or clarified so users understand it is the place to provide either normal planning guidance or retry guidance after a failed sprint run. A recommended contract is:

- label: `Planning or Retry Notes`
- helper or placeholder text that explicitly invites users to paste or summarize retry guidance from the latest failure

## Detailed Contract

### Task Kind Rules

- Canonical stored and validated task kinds remain unchanged.
- The planner should emit only `analysis`, `design`, `implementation`, `testing`, `documentation`, or `refactor`.
- `other` remains part of the schema literal set for compatibility with the shared task model, but it is not valid planner output for sprint task decomposition.
- Known surface mismatches should normalize before they become hard validation failures.
- The same canonicalization helper should apply when `TaskMetadata` parses persisted values, so legacy values such as `review` are read back as canonical `testing`.
- Unknown invalid values must still fail validation.

### Decomposition Rules

- Every sprint task must remain task-local in scope.
- Checklist items must describe local completion conditions or observable evidence.
- Story-level completion language must not be copied into task checklists.
- Artifact targets must describe subsystems, modules, APIs, schemas, or suites rather than exact file paths.
- Structural decomposition defects remain retry-worthy failures, not repair candidates.

### Failure Reporting Rules

- Failed sprint responses should continue to return a concise summary message.
- Failed sprint responses and sprint history should expose `validation_errors` as `list[str]` carrying short actionable retry hints for the UI.
- Raw Pydantic error dictionaries or mixed validation payload shapes should not be exposed on those public surfaces.
- Full failure artifacts should continue to retain raw exception text, detailed validation context, and raw output previews when available.
- The sprint setup form should clearly signal that its freeform notes field can be used for retry guidance after a failed attempt.

## Test Strategy

The test strategy should prove that the contract is harder to break without weakening the quality gates.

### Shared Normalization Tests

Add focused unit coverage in [`utils/task_metadata.py`](../../../utils/task_metadata.py) or its corresponding test module for the shared task-kind canonicalization helper:

- canonical values pass through unchanged
- `review`, ` Review `, and `REVIEW` normalize to `testing`
- `qa` and `validation` normalize to `testing`
- unknown values such as `approval` still fail

### Model-Boundary Tests

Add model-boundary tests showing that both models use the same canonicalization logic:

- `StructuredTaskSpec` validates and stores canonical `testing`
- `TaskMetadata` validates and stores canonical `testing`

### Sprint Runtime Tests

In [`tests/test_sprint_runtime.py`](../../../tests/test_sprint_runtime.py), add or extend tests so that:

- planner output using `task_kind: "review"` succeeds through the runtime path and lands as canonical `testing`
- trivial surface variants with whitespace or casing also succeed
- unknown invalid values still fail validation
- decomposition-quality failures still fail
- failed output artifacts expose actionable `validation_errors` in the public `list[str]` shape

### API and Frontend Contract Tests

Add coverage for the serialization and display path so retry guidance does not regress outside the runtime unit tests:

- in [`tests/test_api_sprint_flow.py`](../../../tests/test_api_sprint_flow.py), add at least one test showing that a failed sprint response and `/sprint/history` both expose `validation_errors` as `list[str]`
- in [`tests/test_sprint_workspace_display.mjs`](../../../tests/test_sprint_workspace_display.mjs), add at least one rendering test showing that retry guidance from `validation_errors` is visible in the sprint UI and that the retry-notes affordance remains understandable after failure

### Existing Quality Tests

Existing decomposition-quality checks should remain unchanged in spirit. The change should not weaken strict behavior for:

- story-level checklist reuse
- duplicate task descriptions
- missing workstream tags
- missing checklist items
- file-path artifact targets

## Acceptance Criteria

- Known surface mismatches for `task_kind` normalize to canonical allowed values before sprint output validation fails.
- The planner prompt explicitly tells the model to use only the six normal sprint task kinds and not emit `other`.
- Structural decomposition problems still fail loudly.
- Failed sprint responses and sprint history expose compact retry guidance in `validation_errors: list[str]`.
- The sprint setup UI makes it clear where retry guidance should be entered for the next attempt.
- Full failure artifacts retain detailed exception and validation context for debugging.

## Implementation Notes for Planning

- Put task-kind canonicalization behind a single shared helper in [`utils/task_metadata.py`](../../../utils/task_metadata.py).
- Reuse that helper from both `StructuredTaskSpec` and `TaskMetadata`.
- Keep the synonym set intentionally small and evidence-based.
- Prefer structured retry hints over longer top-level error strings.
- Do not broaden normalization into structural repair.
