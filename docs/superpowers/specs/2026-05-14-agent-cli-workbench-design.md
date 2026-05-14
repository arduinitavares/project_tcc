# Agent CLI Workbench Design

**Date:** 2026-05-14
**Status:** Approved for planning
**Scope:** Agent-facing CLI, project query surface, Spec Authority gates, workflow command contract

## Summary

The repository needs a first-party CLI that lets autonomous agents use the
platform without scraping the dashboard, hand-writing HTTP calls, or querying
SQLite directly.

The CLI is not just a convenience wrapper. It is an agent-safe workflow and
knowledge interface over the full backbone:

```text
Project Vision
-> Spec Authority
-> Initial Backlog
-> Roadmap
-> User Stories
-> Sprint Planning
-> Sprint Execution
-> Review / Metrics / Learning
```

The critical design requirement is that agents must be able to inspect project
state and Spec Authority before mutating anything. A command that appears to
work while advancing a workflow against stale or wrong authority is worse than a
command that fails.

## Problem Statement

The existing system already has the important internal pieces:

- FastAPI endpoints and a dashboard for humans.
- SQLite-backed business data.
- Workflow session state and FSM transitions.
- Spec versioning, compiled authority, validation evidence, and story pinning.
- Read/query functions for projects, backlog, roadmap structure, features,
  stories, sprint candidates, packets, execution history, failures, and exports.
- Many standalone scripts for narrow maintenance tasks.

Agents still lack one coherent shell interface. That creates several hazards:

- agents may use ad hoc SQL and bypass domain rules
- agents may call HTTP endpoints incorrectly or require a running server
- agents may mutate state without first checking Spec Authority freshness
- agents may act from stale context packs or dashboard-era session state
- scripts remain fragmented and hard to discover
- spec changes on disk may diverge from compiled authority in the database

## Goals

- Provide one coherent `tcc` CLI for autonomous agents and human operators.
- Expose safe read/query commands over existing project data.
- Make Spec Authority status and freshness visible before all important work.
- Preserve FSM, setup, authority, validation, and execution guardrails.
- Keep query commands truly read-only.
- Use stable JSON envelopes and exit codes so agents can reason about results.
- Reuse existing service/query boundaries instead of duplicating business logic.
- Add mutations incrementally after the read/authority surface is proven.

## Non-Goals

- Replacing the FastAPI dashboard.
- Exposing raw SQL in v1.
- Building a complete MCP server in this design.
- Shipping all generate/save workflow commands in the first implementation slice.
- Making context packs a second source of truth.
- Auto-accepting newly compiled authority without an explicit policy.

## Design Principles

### 1. CLI And API Share One Application Boundary

FastAPI and the CLI must be peers over a shared application facade, but the
facade is introduced by implemented use case, not by moving the whole API at
once.

```text
CLI / FastAPI
    -> AgentWorkbenchApplication
        -> ReadProjectionService
        -> Authority service
        -> Phase services
        -> Execution services
        -> Business DB + workflow session store
```

The CLI must not import router handlers or recompose workflow orchestration from
`api.py`. If orchestration currently exists only in `api.py`, move it into the
application facade for that specific command first, then call it from both
transports when the matching API path is in scope.

Phase 1 facade parity is limited to the read projections, authority projection,
context pack, and first task-log use case. Moving all orchestration out of
`api.py` is not part of Phase 1.

### 2. Read Commands Stay Read-Only

`tcc query ...`, `tcc project show`, `tcc authority status`, and
`tcc context pack` must not compile specs, repair cached authority, hydrate
workflow sessions with side effects, or write to session state.

All read commands must go through `ReadProjectionService`. That service opens
read-only business/session access and is forbidden from calling active-project
hydration, compile, backfill, repair, or migration helpers.

If a read detects stale or missing data, it reports that state and returns the
next valid command. It does not silently fix it.

### 3. Spec Authority Is Explicit

Spec Authority is not a single boolean. CLI responses must distinguish:

- source spec hash
- accepted spec version id
- compiled authority id
- compiled authority hash or fingerprint
- compiler version
- prompt hash
- authority acceptance status
- story-pinned spec version where relevant
- stale reason when any part is out of sync

Downstream generation, planning, packets, and execution commands must expose the
authority they are using.

### 4. Mutations Require Fresh State

Mutating commands must check:

- current FSM state
- required prior artifact
- session revision or equivalent freshness token
- relevant draft or attempt id
- entity-specific preconditions, such as active sprint status for task logs

If any check fails, the command exits non-zero with structured JSON.

Authority checks are split by mutation class:

- generation and planning mutations require current accepted project authority
- execution mutations require the story/sprint/task execution artifact's pinned
  authority to be present and internally consistent
- project-level spec drift is a warning during execution unless the execution
  artifact has no valid pin or references missing authority

### 5. Context Packs Are Projections

`context pack` is a fresh, bounded projection for the next agent action. It is
not durable state and not an authority cache.

Each pack must be phase-scoped, size-bounded, and explicit about what it omits.

## Command Surface

The command shape must use stable resource/action groups. JSON is the default
output. Logs and diagnostics go to stderr; machine-readable command output goes
to stdout.

### Orientation And Query Commands

```bash
tcc status --project-id 1
tcc project list
tcc project show --project-id 1
tcc workflow state --project-id 1
tcc workflow next --project-id 1
tcc query structure --project-id 1
tcc query backlog --project-id 1
tcc query features --project-id 1
tcc story show --story-id 42
tcc sprint candidates --project-id 1
```

`tcc status --project-id` is the cheap orientation command. Its payload includes
project identity, DB/session reachability, FSM state, setup status, active or
planned sprint summary, Spec Authority status, disk spec sync status, and
implemented CLI capability groups.

`tcc workflow next --project-id` returns only commands that are both valid for
the current workflow state and implemented in the installed CLI. It considers
FSM state, setup blockers, authority gates, current drafts, active sprint state,
and installed command capability metadata.

### Authority Commands

```bash
tcc authority status --project-id 1
tcc authority versions --project-id 1
tcc authority show --project-id 1 --spec-version-id 3
tcc authority invariants --project-id 1
tcc authority compile --spec-version-id 3
tcc authority accept --project-id 1 --spec-version-id 3 --policy human --decided-by agent
```

`compile` must not imply `accept`. Acceptance is a distinct command and policy
decision.

`authority invariants --project-id` reads the current accepted authority by
default. If multiple compiled versions exist and no authority is accepted, it
returns `ok: false` with remediation to pass `--spec-version-id` or accept an
authority version first.

### Context Commands

```bash
tcc context pack --project-id 1
tcc context pack --project-id 1 --phase sprint-planning
tcc context pack --project-id 1 --phase execution --sprint-id 3
tcc context pack --project-id 1 --phase execution --sprint-id 3 --task-id 42
```

### Future Workflow Commands

These are not in the first implementation slice. They become valid only after
the application facade, authority checks, read-only projections, and one bounded
mutation are stable.

```bash
tcc project create --name "Project" --spec-file specs/app.md
tcc vision generate --project-id 1 --input "..."
tcc vision draft save --project-id 1 --attempt-id 12
tcc backlog generate --project-id 1
tcc backlog draft save --project-id 1 --attempt-id 13
tcc roadmap generate --project-id 1
tcc roadmap draft save --project-id 1 --attempt-id 14
tcc story generate --project-id 1 --requirement "..."
tcc story draft save --project-id 1 --requirement "..." --attempt-id 15
tcc story phase-complete --project-id 1
tcc sprint generate --project-id 1 --selected-story-ids 1,2,3
tcc sprint draft save --project-id 1 --attempt-id 16 --team-name "Team" --start-date 2026-05-14
tcc sprint start --project-id 1 --sprint-id 1
```

### Execution And Review Commands

```bash
tcc story packet --project-id 1 --sprint-id 1 --story-id 7 --flavor agent
tcc task packet --project-id 1 --sprint-id 1 --task-id 9 --flavor agent
tcc task history --project-id 1 --sprint-id 1 --task-id 9
tcc task log --project-id 1 --sprint-id 1 --task-id 9 --expected-status "To Do" --status "In Progress" --changed-by agent
tcc story close-readiness --project-id 1 --sprint-id 1 --story-id 7
tcc story close --project-id 1 --sprint-id 1 --story-id 7 --changed-by agent
tcc sprint close-readiness --project-id 1 --sprint-id 1
tcc sprint close --project-id 1 --sprint-id 1 --changed-by agent
tcc failure show --project-id 1 --artifact-id abc123
tcc snapshot export --project-id 1
tcc metrics export --project-id 1
```

## Response Envelope

Every command must return one stable JSON envelope:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "errors": [],
  "meta": {
    "schema_version": "tcc.cli.v1",
    "command": "tcc authority status",
    "generated_at": "2026-05-14T00:00:00Z"
  }
}
```

Error responses use the same envelope with `ok: false`. Python tracebacks are
debug output only and must not replace the JSON error shape.

Each `errors[]` item uses this schema:

```json
{
  "code": "AUTHORITY_STALE",
  "message": "Spec file changed after the accepted authority was compiled.",
  "details": {},
  "remediation": ["tcc authority status --project-id 1"],
  "exit_code": 4,
  "retryable": false
}
```

Each `warnings[]` item uses this schema:

```json
{
  "code": "PROJECT_SPEC_DRIFT",
  "message": "Project spec changed after this task's pinned authority.",
  "details": {},
  "remediation": ["Finish or replan execution against updated authority."]
}
```

## Exit Codes

- `0`: success
- `1`: unexpected error
- `2`: invalid command or input
- `3`: invalid workflow state
- `4`: Spec Authority gate failure
- `5`: concurrency or stale-context conflict
- `6`: external provider failure for LLM-backed commands

## Context Pack Contract

A context pack must include:

- `project_id`
- `phase`
- `fsm_state`
- `generated_at`
- `source_fingerprint`
- `authority_fingerprint`
- `spec_authority` summary
- `warnings`
- `next_valid_commands`
- `blocked_future_commands`
- `included_sections`
- `omitted_sections`
- `truncation` markers when any list/text is shortened

Default packs must avoid raw spec text, full compiled authority payloads, and
large historical blobs. Full authority inclusion requires `--include authority-full`.
Raw spec inclusion requires `--include raw-spec`; it may appear on stdout only
inside the JSON envelope and must be omitted from text output.

`next_valid_commands` is the intersection of workflow-valid commands and
currently installed CLI capabilities. Commands that are valid in the domain but
not implemented in the current phase go in `blocked_future_commands`.

`source_fingerprint` is a SHA-256 hash over canonical JSON containing the command
name, normalized command arguments, project id, included section names, relevant
business row ids and update timestamps, workflow session revision if available,
and `authority_fingerprint`.

`authority_fingerprint` is a SHA-256 hash over canonical JSON containing
accepted spec version id, authority id, source spec hash, compiled artifact JSON
hash, compiler version, prompt hash, and authority acceptance decision metadata.

Example:

```json
{
  "project_id": 1,
  "phase": "sprint-planning",
  "fsm_state": "SPRINT_SETUP",
  "source_fingerprint": "sha256:...",
  "authority_fingerprint": "sha256:...",
  "spec_authority": {
    "status": "current",
    "accepted_spec_version_id": 3,
    "authority_id": 5,
    "invariant_count": 12,
    "stale_reason": null
  },
  "warnings": [],
  "next_valid_commands": [
    "tcc sprint candidates --project-id 1"
  ],
  "blocked_future_commands": [
    "tcc sprint generate --project-id 1 --selected-story-ids ..."
  ],
  "included_sections": ["project", "workflow", "authority", "sprint_candidates"],
  "omitted_sections": ["raw_spec", "completed_sprint_history"],
  "truncation": []
}
```

## Concurrency And Session Safety

The CLI and dashboard must share the canonical project workflow session for
mutating commands. A separate CLI session would avoid some collisions but would
create a worse split-brain problem where dashboard and CLI disagree about
current phase and drafts.

Mutation safety requires:

- per-project mutation lock
- `--expected-session-revision` or command-specific stale-write token once
  session revision support exists
- stale context rejection for commands that take a freshness token
- attempt id checks for draft saves
- concrete SQLite WAL and write-timeout settings before Phase 2 writes ship

Read commands open a read snapshot. If the projection detects inconsistent row
versions while composing a multi-section response, it retries once; if the second
read is still inconsistent, it returns a structured `READ_SNAPSHOT_CONFLICT`
warning or error instead of silently merging two states.

Phase 2 cannot start until the project lock mechanism, expected-status check for
task logging, and session-revision or stale-write token strategy are specified.

## Spec Authority Gates

Before any mutating command, the application facade must evaluate the authority
gate for that mutation class.

The gate reports:

- `status`: `current`, `stale`, `not_compiled`, `pending_acceptance`, or `missing`
- `accepted_spec_version_id`
- `authority_id`
- `spec_hash`
- `disk_spec_hash` when a file path exists and is readable
- `compiler_version`
- `prompt_hash`
- `stale_reason`
- `allowed_commands`

For generation and planning mutations, a disk spec hash that differs from the
accepted authority source fails with exit code `4` before any write.

For execution mutations, the gate validates the story/sprint/task packet's
pinned authority. Project-level disk drift is returned as a warning, not a
blocker, unless the execution artifact has no pin, references an unavailable
authority, or the pinned authority cannot be matched to the execution context.

### Spec Path Resolution

Spec path hashing never depends on process cwd. Relative `Product.spec_file_path`
and `SpecRegistry.content_ref` values resolve from the repository root. If a
future spec registration records an absolute provenance root, relative paths for
that version resolve from that stored root. Missing or unreadable files produce
structured authority warnings or errors with the resolved path included in
`details`.

## Phased Delivery

### Phase 1: Orientation Read-Only Layer

Implement:

```bash
tcc status --project-id 1
tcc project list
tcc project show --project-id 1
tcc workflow state --project-id 1
tcc workflow next --project-id 1
tcc authority status --project-id 1
tcc authority invariants --project-id 1
tcc story show --story-id 42
tcc sprint candidates --project-id 1
tcc context pack --project-id 1 --phase sprint-planning
```

No workflow mutations. No LLM-backed generation.

### Phase 2: One Bounded Deterministic Mutation

Implement task execution logging:

```bash
tcc task log --project-id 1 --sprint-id 1 --task-id 9 --expected-status "To Do" --status "In Progress" --changed-by agent
```

This proves exit codes, pinned execution authority validation, active-sprint
validation, stale-write protection, and JSON error handling without invoking
LLMs.

### Phase 3: Deterministic Lifecycle Mutations

Add project setup retry, sprint start, story close, sprint close, failure show,
snapshot export, and metrics export.

### Phase 4: LLM-Backed Generation Commands

Add vision, backlog, roadmap, story, and sprint generation only after command
contracts, authority gates, draft attempt ids, and provider error handling are
stable.

## Acceptance Criteria

- FastAPI and CLI call the same `WorkflowApplication` facade for shared behavior.
- Query commands are proven read-only with tests that detect session or DB writes.
- Every CLI command emits the stable JSON envelope.
- Every CLI command returns documented exit codes.
- `authority status` detects missing, stale, pending, and current authority.
- Generation and planning mutations fail on stale project authority before any
  write.
- Execution mutations validate pinned execution authority and warn, rather than
  fail, on unrelated project-level spec drift.
- Draft save commands require attempt ids.
- `context pack` is phase-scoped, bounded, and includes omitted/truncated sections.
- `next_valid_commands` includes only commands implemented in the installed CLI.
- The first bounded mutation rejects inactive, planned-only, completed, or
  wrong-project sprint/task combinations.
- The first bounded mutation requires `--expected-status` and rejects stale task
  status before writing.
- Logs go to stderr; JSON results go to stdout.

## Test Strategy

- Unit-test command parsing and JSON envelope construction.
- Unit-test `errors[]` and `warnings[]` schema construction.
- Unit-test spec path resolution from repository root, not process cwd.
- Unit-test authority status projection against fixture DB states.
- Unit-test generation/planning authority gates separately from execution pinned
  authority gates.
- Unit-test context pack size/truncation and omitted-section reporting.
- Add read-only tests that snapshot session/business DB state before and after
  query commands.
- Add facade parity tests for shared API/CLI use cases once both transports call
  the facade.
- Add FSM guardrail tests for invalid workflow states and stale authority.
- Add exit-code tests for validation errors, workflow state errors, authority
  gate failures, stale-context conflicts, and provider failures.
- Add one integration test for the phase 1 read-only command set.
- Add one integration test for the phase 2 task-log mutation.

## Open Decisions For Planning

- Exact facade module and class names.
- Whether CLI implementation uses `argparse` or `Typer`.
- Exact size budget for default context packs.
- Exact lock implementation for project mutations.
- Exact session revision field or compare-and-swap mechanism.
- Whether HTTP transport is supported later under the same command contract.
- Whether an MCP server should wrap the same facade after CLI v1 proves the
  command contract.
