# Failure-Aware Interview Runtime Design

**Date:** 2026-03-28
**Status:** Approved for planning
**Scope:** Reusable interview-runtime pattern, implemented first in story mode

## Summary

The current interview/refinement flow mixes four different concerns into a single implicit sequence:

- audit history of attempts
- reusable draft state
- user feedback state
- retry behavior

That coupling works only on the happy path where every previous attempt produces a valid draft. It breaks when the latest attempt fails due to transport, provider, truncation, invalid JSON, or schema-validation issues, because the system treats "latest attempt" as both history and refinement baseline.

This design introduces a reusable interview-runtime pattern that separates those responsibilities explicitly:

- `attempt_history` records every attempt for audit and UI history
- `draft_projection` tracks only the latest schema-valid, semantically reusable draft
- `feedback_projection` preserves ordered user feedback independently of model success/failure
- `request_projection` stores the exact assembled request used for invocation so transient failures can retry deterministically

The first implementation slice applies this pattern to story mode. The design intentionally uses generic naming and contracts so vision, backlog, and roadmap interview phases can adopt the same runtime model later.

## Problem Statement

In interview mode, each new turn can depend on the previous one. That dependency is only valid when the previous attempt produced a usable draft.

Today, story mode effectively reads "latest attempt" as the source for multiple behaviors:

- previous draft injection during refinement
- save eligibility
- UI interpretation of the current state

This causes failure contamination:

- a failed attempt can be treated as refinement input even though it is not a draft
- user feedback can become coupled to whether the last model call succeeded
- retries after transient failures can accidentally become refinements of broken output
- generation history, refinement baseline, and retry semantics are not clearly distinguishable

The design must make interview mode failure-aware, not just happy-path aware.

## Goals

- Separate successful reusable draft state from failed attempt history.
- Preserve user feedback independently of model success or failure.
- Make retries idempotent for transient failures by replaying the same input.
- Ensure prompt assembly reads reusable projections, not raw attempt history.
- Keep all attempts visible in history for transparency and auditability.
- Implement the pattern in story mode first without blocking future adoption in vision, backlog, and roadmap phases.

## Non-Goals

- Rewriting all interview-style phases in one change.
- Introducing full event sourcing for the runtime.
- Reconstructing exact historical request snapshots for old attempts that never stored them.
- Making save behavior depend on the latest attempt rather than the latest reusable draft.
- Sending the entire feedback thread on every prompt.

## Source Framing

This design is grounded in the current interview/runtime surfaces:

- [`services/story_runtime.py`](../../../services/story_runtime.py)
- [`api.py`](../../../api.py)
- [`frontend/project.js`](../../../frontend/project.js)
- [`frontend/project.html`](../../../frontend/project.html)

The current implementation already keeps attempt history and failure artifacts, but it still couples refinement and save behavior to "latest attempt wins". This design replaces that implicit coupling with explicit projections.

## Design Principles

### Prompt Assembly Reads Projections, Not Raw History

This is the central design rule.

Prompt assembly must never inspect raw attempt history and decide that the most recent attempt is automatically the next refinement baseline. Instead, prompt assembly must read the current reusable projections:

- the latest reusable draft
- the current unresolved feedback slice
- the stable context required by the phase

### Storage Model Is Cumulative, Prompt Model Is Selective

The runtime should preserve a complete ordered feedback and attempt history for auditability. Prompt assembly should send only the minimal working subset needed for the next turn.

### Retry Is Explicit, Not Implicit

Retrying a transient transport/provider failure is a different user action from refining a draft. The runtime and UI should expose those as separate behaviors.

## Runtime Model

The reusable runtime is keyed by `(phase, subject_key)`.

- `phase` identifies the interview-style artifact type, such as `story`, `vision`, `backlog`, or `roadmap`
- `subject_key` identifies the item being refined inside that phase

For story mode, `subject_key` is `parent_requirement`.

```json
{
  "interview_runtime": {
    "story": {
      "<parent_requirement>": {
        "attempt_history": [],
        "draft_projection": {},
        "feedback_projection": {},
        "request_projection": {}
      }
    }
  }
}
```

## Runtime Responsibilities

### 1. `attempt_history`

`attempt_history` is an append-only ledger of everything that happened for a given `(phase, subject_key)`.

It exists for:

- auditability
- UI generation history
- debugging and analytics

It does not exist for:

- refinement baseline selection
- retry payload reconstruction
- save eligibility

Each attempt should capture at least:

- `attempt_id`
- `created_at`
- `trigger`
- `request_snapshot_id`
- `base_draft_attempt_id`
- `included_feedback_ids`
- `classification`
- `is_reusable`
- `retryable`
- `draft_kind` when reusable
- `output_artifact`
- failure metadata such as `failure_stage`, `failure_artifact_id`, `failure_summary`, and `raw_output_preview`

### 2. `draft_projection`

`draft_projection` stores the latest semantically reusable output for the subject.

It is the only prior model output eligible for "previous draft to refine" injection.

Recommended fields:

- `latest_reusable_attempt_id`
- `kind`
- `is_complete`
- `updated_at`

The source of truth for the reusable artifact should be the referenced attempt in `attempt_history`. If the UI needs faster access, minimal denormalized fields may be mirrored, but the attempt remains canonical.

`kind` should be explicit:

- `complete_draft`
- `incomplete_draft`
- `clarification_only`

### 3. `feedback_projection`

`feedback_projection` stores the ordered user feedback thread independently of model success/failure.

Each feedback item should record:

- `feedback_id`
- `text`
- `created_at`
- `status`
- `absorbed_by_attempt_id`

`status` is one of:

- `unabsorbed`
- `absorbed`

The runtime may also keep a lightweight unresolved summary or cursor for prompt assembly, but the system of record remains the ordered feedback thread.

### 4. `request_projection`

`request_projection` stores the exact assembled request used for the most recent invocation so transient failures can support deterministic replay.

Recommended fields:

- `request_snapshot_id`
- `payload`
- `request_hash`
- `created_at`
- `draft_basis_attempt_id`
- `included_feedback_ids`
- `context_version`

`request_projection` must store both:

- the frozen payload actually sent to the agent
- the assembly provenance that explains how that payload was formed

## Reuse And Failure Classification

### Reuse Rule

The next interview/refinement turn should reuse the last schema-valid, content-meaningful draft. It should not reuse attempts that failed for infrastructure or transport reasons.

This is a semantic reuse rule, not a simple `success` flag rule and not a simple `is_complete` rule.

### Attempt Classification Taxonomy

Each completed invocation should receive one classification:

- `reusable_content_result`
- `nonreusable_schema_failure`
- `nonreusable_transport_failure`
- `nonreusable_provider_failure`

Derived flags:

- `is_reusable = classification == "reusable_content_result"`
- `retryable = classification in {"nonreusable_transport_failure", "nonreusable_provider_failure"} and request_projection exists`

### Story-Mode Reusable Semantics

Story mode v1 should use a deliberately conservative reuse boundary.

An output is reusable when it is:

- schema-valid against `UserStoryWriterOutput`
- and has non-empty `user_stories`, or non-empty `clarifying_questions`

This includes outputs where `is_complete=false`.

These are valid reusable kinds:

- `complete_draft`
  - schema-valid
  - meaningful `user_stories`
  - `is_complete=true`
- `incomplete_draft`
  - schema-valid
  - meaningful `user_stories`
  - `is_complete=false`
- `clarification_only`
  - schema-valid
  - no meaningful reusable stories
  - non-empty `clarifying_questions`
  - `is_complete=false`

These are non-reusable:

- network failures
- timeouts
- provider/runtime exceptions
- rate-limit, credit, or auth failures
- invalid JSON
- truncation or EOF
- schema-invalid output that cannot be normalized safely

The distinction is intentional:

- content failure can be useful interview signal
- infrastructure failure should be logged, not recycled into refinement context

## Prompt Assembly Rules

### `Generate / Refine`

`Generate / Refine` is the normal content iteration path.

It should:

- append new user feedback to `feedback_projection` before invocation
- read stable phase context
- read the current `draft_projection`, if present
- read only the relevant unabsorbed feedback slice
- assemble a request payload
- freeze that payload into `request_projection`

It must not:

- read the latest raw attempt directly
- inject a failed output artifact as the refinement baseline

### `Retry same input`

`Retry same input` is available only when:

- the latest attempt is non-reusable and retryable
- and a valid `request_projection` exists for safe replay

It should:

- replay the frozen `request_projection.payload` exactly
- create a new attempt entry
- avoid rebuilding the request from changed runtime state
- avoid appending duplicate feedback entries
- avoid injecting the failed output as previous draft context

This makes transient retries idempotent with respect to the user-visible request semantics.

## Feedback Absorption Rules

Feedback must be preserved independently of invocation success.

Operational rules:

- every user feedback turn is stored in order under the subject
- included feedback remains `unabsorbed` until a reusable content result is returned
- when a reusable result is produced, the included feedback items become `absorbed` with `absorbed_by_attempt_id=<winning attempt>`
- if a retry fails again, the included feedback remains `unabsorbed`
- new user feedback after a reusable result creates new unabsorbed entries

This means:

- storage is cumulative
- prompt assembly is selective

The model sees only the latest reusable draft plus the minimal unresolved feedback subset, not the entire interview thread.

## Story-First Rollout

The architecture is generic, but the first implementation slice is story mode.

Story mode should adopt the generic runtime behind a story-specific adapter:

- `phase = "story"`
- `subject_key = parent_requirement`

The existing story endpoints can remain the public surface initially, but their behavior should be backed by `interview_runtime.story[parent_requirement]` rather than legacy "latest attempt wins" semantics.

For story mode, the new sources of truth become:

- history UI: `attempt_history`
- refine baseline: `draft_projection.latest_reusable_attempt_id`
- retry availability: latest retryable failed attempt with a valid `request_projection`
- save eligibility and save source: the reusable draft referenced by `draft_projection`

## Compatibility And Migration

The runtime state lives in workflow session state, so migration should be lightweight and forward-compatible.

### On-Read Migration

If `interview_runtime.story[parent_requirement]` is missing but legacy `story_attempts` exists:

- hydrate a runtime view from legacy attempts
- classify old attempts conservatively
- derive `draft_projection` from the latest reusable historical attempt, not the latest successful attempt
- initialize an empty feedback thread if no separate feedback state exists

### On-Write Persistence

On the next write:

- persist the new `interview_runtime.story[parent_requirement]` structure
- if compatibility fields must still be written short-term, treat them as derived mirrors of the new runtime state only

Legacy fields must never remain a second source of truth.

### Historical Retry Limits

Do not pretend that old attempts can support deterministic retry if no historical request snapshot exists.

Old attempts without replayable request state should:

- remain visible in history
- remain classifiable
- not expose `Retry same input`

## UI And API Behavior

### UI Actions

Story mode should expose two distinct actions:

- `Generate / Refine`
  - uses the latest reusable draft, if one exists
  - applies current feedback as a refinement turn
- `Retry same input`
  - replays the exact last failed request payload and preserved feedback
  - appears only when the latest attempt is non-reusable, retryable, and has a replayable request snapshot

### History And Transparency

Generation history should remain complete and visible. Suggested attempt badges:

- reusable draft
- clarification result
- retryable failure
- non-retryable schema failure

For transparency, the details panel may default to the latest attempt. However, any "use this as baseline" behavior must come only from projections, never from the display default.

### Save Behavior

Save must read from `draft_projection`, not from the latest attempt.

Consequences:

- a retryable failure after a good draft must not invalidate the good draft as the save baseline
- if no reusable draft exists, save must remain unavailable even if many failed attempts exist in history

### API Surface Expectations

The story API should support the frontend in querying:

- full attempt history
- current reusable draft projection
- pending feedback count or unresolved feedback slice
- retry availability and target attempt id

The public endpoint names can stay story-specific in the first rollout, but the returned data should reflect the generic runtime model.

## Testing Strategy

Tests should focus on projection boundaries and behavior, not incidental legacy storage details.

### Classification And Reuse

- schema-valid incomplete output with stories is reusable
- schema-valid clarification-only output is reusable only when `is_complete=false`
- invalid JSON, truncation, or EOF is `nonreusable_schema_failure`
- provider timeout/rate-limit/auth/credit failures are non-reusable provider/transport failures
- retryable is false when no replayable request snapshot exists

### Projection Updates

- reusable result promotes `draft_projection`
- non-reusable failure leaves `draft_projection` unchanged
- included feedback is absorbed only on reusable result
- failed retry leaves included feedback unabsorbed

### Retry Semantics

- `Retry same input` replays the frozen payload exactly
- retry does not append duplicate feedback entries
- retry does not inject failed output as the previous draft
- retry is unavailable when the replayable request snapshot is missing

### Save Semantics

- save reads the latest reusable draft, not the latest attempt
- a retryable failure after a reusable draft does not block save of that reusable draft
- if no reusable draft exists, save is unavailable even if history contains many failed attempts

### API And UI Contract

- history badges reflect attempt classification
- `Generate / Refine` and `Retry same input` availability match backend state
- the latest attempt may be shown by default for transparency, while refinement and save behavior follow projections only

## Recommended Implementation Boundary

This design should be implemented as a reusable interview-runtime pattern with a story-mode-first rollout.

That means:

- architecture and naming should stay generic
- the first production slice should only change story mode
- story mode should prove the pattern before other interview-style phases adopt it

This balances correctness, reuse, and delivery risk:

- it fixes the real failure-aware design problem now
- it avoids overcommitting to full event sourcing
- it creates a clean platform-level runtime pattern for later phases
