# Agentic CLI Roadmap Design

**Date:** 2026-05-15
**Status:** Approved for specification review
**Scope:** Full `agileforge` CLI roadmap for autonomous agents

## Summary

AgileForge needs a complete CLI-first agent interface. Agents must be able to
create projects, inspect state, generate drafts, save reviewed work, execute
sprints, log task progress, close work, and run guarded recovery operations
without MCP, browser interaction, hand-written HTTP calls, or a running web
server.

The CLI is the product interface for agents. It must expose the full workflow
through typed, stable, JSON-default commands that preserve AgileForge guardrails
instead of bypassing them.

## Problem Statement

The current CLI is intentionally Phase 1 read-only. It exposes project,
workflow, authority, story, sprint, context, and status inspection commands, but
it cannot create projects or drive the workflow forward.

The project already has the underlying pieces for a fuller interface:

- FastAPI routes and dashboard flows for humans.
- `AgentWorkbenchApplication` as the first agent-facing facade.
- Read projections and context packs for safe inspection.
- Project setup orchestration in `services/setup_service.py`.
- Phase services and tests for vision, backlog, roadmap, stories, sprints,
  task execution, story close, sprint close, and recovery paths.

Agents must not be sent through the dashboard or FastAPI as a workaround.
They need a coherent shell contract that is safe to run from any project
directory through the central AgileForge repo shim.

## Goals

- Provide one complete `agileforge` CLI roadmap for autonomous agents.
- Keep the CLI independent of FastAPI route handlers and browser workflows.
- Use `AgentWorkbenchApplication` as the stable application facade.
- Keep query commands read-only.
- Make all mutation commands explicit, typed, reviewable, and guarded.
- Default every command to JSON output backed by Pydantic contracts.
- Preserve manual review checkpoints before canonical state changes.
- Support central-repo execution from arbitrary caller project directories.
- Include full admin and recovery operations as normal guarded commands.
- Harden the CLI command contract before adding broad mutation coverage.
- Make every mutation idempotent and recoverable before exposing it to agents.
- Phase implementation so each command promotes its use case into a shared
  service boundary before exposing it through CLI.

## Non-Goals

- Building an MCP server.
- Making the CLI depend on a running HTTP server.
- Routing agents through the dashboard.
- Calling FastAPI route functions from CLI commands.
- Auto-saving generated work into canonical state.
- Hiding destructive commands behind a separate admin namespace.
- Rewriting all existing API orchestration in one implementation slice.

## Decisions

- The roadmap scope is the full agentic CLI, not only `project create`.
- The implementation strategy is facade-first.
- Generated work always uses manual checkpoints.
- JSON is the default output format.
- Pydantic models define command payloads, warnings, errors, and schemas.
- Guardrails are hybrid: draft commands are validated, canonical mutations are
  strongly guarded.
- Destructive commands are listed in capabilities by default, but execution
  requires noninteractive confirmation flags and command-specific stale-state
  guards.
- Contract hardening is the next slice before broad lifecycle mutations.
- Every non-dry-run mutating command requires `--idempotency-key`.
- Mutation guards use explicit expected values rather than one ambiguous
  fingerprint.
- `--expected-authority-version` means the accepted authority decision id from
  the latest accepted `SpecAuthorityAcceptance` row. Envelopes also expose the
  related `spec_version_id` and `authority_id`.
- `--changed-by` is optional on every mutation, defaults to `cli-agent`, accepts
  a non-empty stable actor string, and appears in audit records plus domain
  history where that domain already tracks actors.

## Architecture

The CLI transport must stay thin:

```text
cli/main.py
    -> AgentWorkbenchApplication
        -> use case services
        -> phase services
        -> repositories
        -> business DB and workflow session store
```

`cli/main.py` is responsible for argument parsing, invoking a facade method,
printing a typed envelope, and returning the correct exit code. It must not
import FastAPI route handlers, call HTTP endpoints, or duplicate workflow
orchestration.

Each new mutating command must first promote its business operation into a
focused use case service or facade method. For example, `project create` must
move project creation and setup orchestration behind the application boundary.
The CLI calls that boundary directly. The API can later call the same boundary
where parity is useful.

This keeps the CLI and API as peers over shared application behavior while
avoiding a large rewrite of `api.py`.

## Mutation Contract Boundary

Every mutation command must be defined by a request model, a response model, a
guard policy, an idempotency policy, and a transaction/recovery policy before it
is exposed in the parser.

The standard non-dry-run mutation flow is:

```text
parse args
-> build typed request
-> resolve caller-relative paths
-> persist or replay mutation ledger record
-> load current project/workflow/authority context
-> run guard checks
-> execute use case service
-> finalize mutation ledger and audit event
-> return typed mutation envelope
```

Non-dry-run mutation request models must include:

- `idempotency_key`
- `correlation_id`
- `changed_by`
- command-specific arguments
- command-specific guard tokens

Preview request models must include `dry_run: true`, optional `dry_run_id`,
optional `correlation_id`, optional `changed_by`, command-specific arguments,
and command-specific guard tokens.

### Dry-Run Idempotency Semantics

The CLI must support `--dry-run` for mutation commands. A dry run validates the
request and guard checks, returns the current before snapshot, and performs no
domain writes.

Dry-runs do not create mutation ledger rows, do not consume idempotency keys,
and do not participate in mutation response replay. The parser must reject
`--idempotency-key` when `--dry-run` is present. Agents may pass optional
`--dry-run-id` for tracing preview runs, but `dry_run` and `dry_run_id` are not
part of the canonical mutation request hash.

If deterministic prediction is unavailable, the dry-run envelope must set
`preview_available: false` and explain why. Non-deterministic commands,
including model-backed generation and authority compilation, must not call model
providers during dry runs.

### Idempotency And Durable Mutation Protocol

`correlation_id` is for tracing. It is not a deduplication mechanism. Every
non-dry-run mutating command must require `--idempotency-key` and persist a
mutation ledger record before domain writes start.

The mutation ledger must store:

- command name
- idempotency key
- canonical request hash
- project id when applicable
- correlation id
- changed-by actor
- status: `pending`, `succeeded`, `validation_failed`,
  `guard_rejected`, `domain_failed_no_side_effects`, or
  `recovery_required`
- guard inputs
- before snapshot
- after snapshot when available
- response envelope when available
- recovery action when recovery is required
- timestamps

The uniqueness boundary is command name plus idempotency key. If the same
command receives the same key and the same request hash, it must replay the
stored response or resume deterministic recovery. If the same command receives
the same key with a different request hash, it must fail with
`IDEMPOTENCY_KEY_REUSED`.

Idempotency keys must be ASCII strings between 8 and 128 characters using only
letters, digits, `.`, `_`, `:`, and `-`. Agents must generate a fresh key per
non-dry-run command attempt. Phase 2A must not expire mutation ledger records;
a later archival policy may move old rows only after preserving replay and audit
requirements.

Invalid argparse input does not create a ledger row. For non-dry-run mutations,
the ledger row is created or loaded before guard checks. Guard-rejected and
domain-validation-failed requests consume the idempotency key for that exact
request hash and replay the same structured failure on retry. Retrying with
updated guard tokens or corrected arguments requires a new idempotency key.

Ledger status meanings are:

- `pending`: ledger row exists and the command is inside its declared write
  protocol.
- `succeeded`: declared writes completed and the stored response can be replayed.
- `validation_failed`: typed request validation or deterministic preflight
  failed after parser acceptance and before domain writes.
- `guard_rejected`: stale-state, stale-fingerprint, confirmation, or authority
  guard failed before domain writes.
- `domain_failed_no_side_effects`: the use case failed before declared domain
  writes began, such as a model-provider failure before artifact persistence.
- `recovery_required`: some declared side effect may have occurred, finalization
  failed, or the command cannot prove that all declared writes completed.

The canonical request hash includes command name, command version, normalized
explicit arguments, defaulted arguments, resolved file paths, file content hashes
for file inputs, guard tokens, and `changed_by`. It excludes the idempotency key,
`correlation_id`, generated timestamps, dry-run fields, process cwd after path
resolution, and environment-derived values that are not explicit command inputs.

The ledger is also the audit source for CLI mutations. A command must not start
domain writes if it cannot persist the initial ledger row. A canonical mutation
is not successful until the final response is stored in the ledger. If side
effects occur but finalization fails, the command must return
`MUTATION_RECOVERY_REQUIRED` when possible, and the next invocation with the
same idempotency key must produce a deterministic recovery or replay outcome.
`mutation_event_id` is the mutation ledger primary key and the audit event id.

Recovery must be operator-visible:

```bash
agileforge mutation show --mutation-event-id 101
agileforge mutation resume --mutation-event-id 101
agileforge mutation list --project-id 1 --status recovery_required
```

When a retry with the same command and idempotency key sees
`recovery_required`, it may automatically resume only if the ledger row declares
the recovery action safe and deterministic. Otherwise it must return
`MUTATION_RECOVERY_REQUIRED` with a structured `mutation resume` remediation.

### Cross-Store Mutation Protocol

Each mutation use case must document its write boundary. Business database
writes and workflow session writes may not share one SQLite transaction in the
current architecture. A cross-store mutation must either complete all declared
writes or leave a durable recovery record that makes the next command
deterministic.

Before Phase 2B can ship `project create`, Phase 2A must define and test:

- pending mutation ledger creation before product/spec/session writes
- idempotent replay by command and request hash
- ordered write steps for product, spec registry, authority compilation,
  pending compiled authority artifact persistence, and workflow session
  initialization
- explicit recovery states for each step boundary
- response replay after success
- deterministic retry behavior after timeout or partial failure
- no `SpecAuthorityAcceptance` row creation during `project create`

A command must not claim atomicity across stores unless tests prove it.

## Central Repo And Caller Paths

The machine-level shim runs the central AgileForge repo from any caller
directory. The CLI must preserve that model:

- File inputs such as `--spec-file specs/app.md` resolve relative to the
  caller's current working directory unless already absolute.
- Persisted file paths must be canonical absolute paths.
- AgileForge internal resources, instructions, templates, migrations, and
  config defaults resolve from the central repo root, not from the caller cwd.
- Mutation commands must have regression coverage proving they work outside the
  AgileForge repository.

## Command Taxonomy

The roadmap uses lifecycle namespaces:

```text
agileforge project ...
agileforge workflow ...
agileforge authority ...
agileforge vision ...
agileforge backlog ...
agileforge roadmap ...
agileforge story ...
agileforge sprint ...
agileforge task ...
agileforge artifact ...
agileforge mutation ...
agileforge schema ...
agileforge command ...
agileforge help ...
agileforge doctor
agileforge capabilities
```

Commands follow a manual checkpoint grammar:

```text
generate -> draft show -> draft save
```

Draft generation may persist attempt artifacts, but it must not update the
canonical phase artifact. Canonical state changes happen only through explicit
verbs such as `save`, `accept`, `start`, `log`, `close`, `reset`, or `delete`.

### Project Commands

```bash
agileforge project list
agileforge project show --project-id 1
agileforge project create --name "Project" --spec-file specs/app.md --idempotency-key create-project-20260515-001
agileforge project setup retry --project-id 1 --spec-file specs/app.md --idempotency-key setup-retry-1-001
agileforge project delete --project-id 1 --expected-context-fingerprint abc123 --confirm-project-id 1 --confirm-project-name "Project" --reason "duplicate project" --idempotency-key delete-project-1-001
```

`project create` initializes the project, links the specification, compiles a
reviewable pending authority artifact, initializes workflow state, and returns
the next valid commands. It must not auto-accept authority or auto-run vision.
The next canonical step is an explicit authority review/accept command. It does
not create a `SpecAuthorityAcceptance` row and does not require a running web
server.

`project delete` is a recoverable soft delete in the CLI roadmap. Irreversible
purge requires a separate command and a later, stricter design.

### Workflow Commands

```bash
agileforge workflow state --project-id 1
agileforge workflow next --project-id 1
agileforge workflow reset --project-id 1 --expected-state VISION_REVIEW --expected-context-fingerprint def456 --scope setup,vision --to-state SETUP_REQUIRED --reason "bad setup input" --confirm-project-id 1 --idempotency-key workflow-reset-1-001
```

Workflow reset is listed in capabilities by default, but execution requires
expected current state, context fingerprint, explicit reset scope, target state,
reason, and confirmation flags. Its response must list invalidated artifacts,
preserved artifacts, recovery commands, and before/after workflow state.

### Authority Commands

```bash
agileforge authority status --project-id 1
agileforge authority invariants --project-id 1
agileforge authority compile --project-id 1 --spec-file specs/app.md --idempotency-key authority-compile-1-001
agileforge authority show --project-id 1 --spec-version-id 3
agileforge authority accept --project-id 1 --spec-version-id 3 --expected-artifact-fingerprint abc123 --idempotency-key authority-accept-1-001
```

Authority compilation creates reviewable authority output. Accepting authority
is an explicit canonical mutation. The accepted authority version exposed to
guards is the accepted `SpecAuthorityAcceptance.id`; command outputs must also
include `spec_version_id` and `authority_id` so agents can explain provenance.

### Vision, Backlog, And Roadmap Commands

```bash
agileforge vision generate --project-id 1 --input "optional guidance" --idempotency-key vision-generate-1-001
agileforge vision draft show --project-id 1 --attempt-id 12
agileforge vision draft save --project-id 1 --attempt-id 12 --expected-state VISION_REVIEW --expected-artifact-fingerprint abc123 --expected-authority-version 3 --idempotency-key vision-save-12-001

agileforge backlog generate --project-id 1 --idempotency-key backlog-generate-1-001
agileforge backlog draft show --project-id 1 --attempt-id 13
agileforge backlog draft save --project-id 1 --attempt-id 13 --expected-state BACKLOG_REVIEW --expected-artifact-fingerprint def456 --expected-authority-version 3 --idempotency-key backlog-save-13-001

agileforge roadmap generate --project-id 1 --idempotency-key roadmap-generate-1-001
agileforge roadmap draft show --project-id 1 --attempt-id 14
agileforge roadmap draft save --project-id 1 --attempt-id 14 --expected-state ROADMAP_REVIEW --expected-artifact-fingerprint ghi789 --expected-authority-version 3 --idempotency-key roadmap-save-14-001
```

These phases always generate drafts first. Saving a draft requires a reviewed
attempt id and stale-context guard.

### Story Commands

```bash
agileforge story generate --project-id 1 --requirement "checkout as guest" --idempotency-key story-generate-1-001
agileforge story draft show --project-id 1 --attempt-id 15
agileforge story draft save --project-id 1 --attempt-id 15 --expected-state STORY_REVIEW --expected-artifact-fingerprint jkl012 --expected-authority-version 3 --idempotency-key story-save-15-001
agileforge story show --story-id 7
agileforge story packet --project-id 1 --sprint-id 3 --story-id 7 --flavor agent
agileforge story close-readiness --project-id 1 --sprint-id 3 --story-id 7
agileforge story close --project-id 1 --sprint-id 3 --story-id 7 --expected-context-fingerprint mno345 --idempotency-key story-close-7-001
agileforge story phase-complete --project-id 1 --expected-state STORY_REVIEW --idempotency-key story-phase-complete-1-001
```

Story commands must preserve authority pinning and validation evidence. Closing
a story must verify task state, sprint membership, and review readiness.

### Sprint Commands

```bash
agileforge sprint candidates --project-id 1
agileforge sprint generate --project-id 1 --selected-story-ids 1,2,3 --idempotency-key sprint-generate-1-001
agileforge sprint draft show --project-id 1 --attempt-id 20
agileforge sprint draft save --project-id 1 --attempt-id 20 --team-name "Core" --start-date 2026-05-18 --expected-state SPRINT_REVIEW --expected-artifact-fingerprint pqr678 --expected-authority-version 3 --idempotency-key sprint-save-20-001
agileforge sprint start --project-id 1 --sprint-id 3 --expected-state SPRINT_PLANNED --idempotency-key sprint-start-3-001
agileforge sprint close --project-id 1 --sprint-id 3 --expected-state SPRINT_ACTIVE --expected-context-fingerprint stu901 --idempotency-key sprint-close-3-001
```

Sprint save and start are canonical mutations. They must fail if the selected
stories, authority status, or workflow state changed after review.

### Task Commands

```bash
agileforge task packet --project-id 1 --sprint-id 3 --task-id 9 --flavor agent
agileforge task history --project-id 1 --sprint-id 3 --task-id 9
agileforge task log --project-id 1 --sprint-id 3 --task-id 9 --expected-status "To Do" --status "In Progress" --changed-by agent --idempotency-key task-log-9-001
```

Task logging is a canonical execution mutation. It requires the expected prior
task status to prevent stale progress updates.

### Artifact And Schema Commands

```bash
agileforge artifact list --project-id 1
agileforge artifact show --project-id 1 --artifact-id 44
agileforge artifact clear --project-id 1 --artifact-id 44 --confirm-artifact-id 44 --reason "obsolete failed run" --idempotency-key artifact-clear-44-001

agileforge schema list
agileforge schema show VisionDraftResult
agileforge help command vision generate --format json
```

Schema commands expose Pydantic contract documentation for agents. Artifact
clear is destructive and requires explicit confirmation.

### Operational Contract Commands

```bash
agileforge doctor
agileforge schema check
agileforge capabilities
agileforge command schema "agileforge vision generate"
agileforge mutation show --mutation-event-id 101
agileforge mutation resume --mutation-event-id 101
agileforge mutation list --project-id 1 --status recovery_required
```

`doctor` reports runtime health: database reachability, storage schema
readiness, central repo resolution, caller cwd, configured model providers, and
session store reachability.

`capabilities` reports installed commands, command versions, stability,
mutation support, and supported storage/schema versions.

`command schema` returns the input argument schema, output envelope schema,
guard policy, idempotency policy, possible error codes, exit codes, and
producer commands for required guard tokens.

`mutation show`, `mutation resume`, and `mutation list` expose recovery state
from the mutation ledger without requiring agents to inspect storage directly.

## Guardrails

Read commands must remain read-only. They may detect missing, stale, or invalid
state, but they must not compile specs, repair authority, hydrate mutable
session state, or write to the database.

Draft commands may create attempt records and failure artifacts. They must not
replace accepted/canonical phase output.

Canonical mutations must require the reviewed artifact identity and enough
expected state to fail closed when stale:

- `--attempt-id`, `--draft-id`, `--sprint-id`, `--story-id`, or `--artifact-id`
- `--idempotency-key`
- `--expected-state` when the workflow FSM matters
- `--expected-artifact-fingerprint` when reviewed draft content matters
- `--expected-context-fingerprint` when the reviewed state spans multiple
  projections such as workflow, authority, sprint, story, and task state
- `--expected-authority-version` when Spec Authority matters
- phase-specific expected values such as `--expected-status`

If the current state does not match the expected state, the command returns a
typed stale-context error and remediation commands.

The guard contract must not overload one fingerprint field with several
meanings. Artifact fingerprints protect reviewed content. Context fingerprints
protect reviewed multi-resource state. Authority version protects the accepted
Spec Authority lineage.

The v1 concurrency model is optimistic. Commands are safe under overlapping
agent attempts by rejecting stale writes; they do not guarantee serializable
multi-agent scheduling across independent resources. If later requirements need
stronger concurrency, add explicit row versions or a locking strategy before
claiming that support.

Destructive commands must require explicit confirmation flags. The CLI must not
prompt interactively by default because agents need deterministic behavior.
Missing confirmation flags produce structured errors with the required flags.
Destructive commands must also require a non-empty `--reason`.

All canonical and destructive mutations must return before/after summaries
and enough audit metadata to explain what changed and why.

Every canonical and destructive mutation must append an audit event containing
the command, correlation id, changed-by value, guard inputs, before snapshot,
after snapshot, outcome, timestamp, and project id when applicable.

### Guard Token Provenance

Each command schema must declare its required guard fields. The parser must
reject missing required guard fields before calling the facade.

| Command | Required Guards | Producer Command | Fingerprint Payload | Compare Point |
| --- | --- | --- | --- | --- |
| `project create` | `idempotency_key`, request hash | none | canonical request: project name, canonical spec path, spec file hash | before product row creation |
| `project setup retry` | `idempotency_key`, `expected_state`, `expected_context_fingerprint` | `workflow state`, `status` | project id, workflow state, setup status, spec path, accepted authority version | after loading project and session, before setup writes |
| `authority accept` | `idempotency_key`, `expected_artifact_fingerprint` | `authority show` | compiled authority artifact, spec version id, authority id, compiler version, prompt hash | in the business DB transaction before acceptance row insert |
| `vision/backlog/roadmap draft save` | `idempotency_key`, `attempt_id`, `expected_state`, `expected_artifact_fingerprint`, `expected_authority_version` | phase `draft show`, `authority status` | draft artifact content, attempt id, phase, accepted authority decision id | after loading draft and authority, before canonical phase write |
| `story draft save` | `idempotency_key`, `attempt_id`, `expected_state`, `expected_artifact_fingerprint`, `expected_authority_version` | `story draft show`, `authority status` | draft story payload, validation evidence, attempt id, accepted authority decision id | after loading draft and authority, before story persistence |
| `sprint draft save` | `idempotency_key`, `attempt_id`, `expected_state`, `expected_artifact_fingerprint`, `expected_authority_version` | `sprint draft show`, `authority status` | sprint draft payload, selected story ids, team, dates, accepted authority decision id | after loading selected stories and authority, before sprint persistence |
| `sprint start` | `idempotency_key`, `sprint_id`, `expected_state`, `expected_context_fingerprint` | `workflow state`, `sprint draft show` or `sprint show` | workflow state, planned sprint row, selected story ids, task ids | after loading sprint and workflow state, before start transition |
| `task log` | `idempotency_key`, `expected_status` | `task history` or `task packet` | task id, current status, sprint id, story id, latest task history sequence | in the business DB transaction before task history insert |
| `story close` | `idempotency_key`, `story_id`, `expected_context_fingerprint` | `story close-readiness` | story id, sprint id, task statuses, sprint membership, close readiness result | after loading close readiness, before close mutation |
| `sprint close` | `idempotency_key`, `sprint_id`, `expected_state`, `expected_context_fingerprint` | `sprint status` or `sprint close-readiness` | sprint id, workflow state, story close states, task statuses, sprint membership | after loading sprint readiness, before close mutation |
| `workflow reset` | `idempotency_key`, `expected_state`, `expected_context_fingerprint`, `scope`, `reason`, confirmations | `status`, `workflow state` | project id, workflow state, setup status, accepted authority version, active sprint/story/task summary | after loading all affected resources, before invalidation writes |
| `project delete` | `idempotency_key`, `expected_context_fingerprint`, confirmations, `reason` | `status`, `project show` | project id, name, workflow state, active sprint/story/task summary, accepted authority version | after loading project and active state, before soft delete |
| `artifact clear` | `idempotency_key`, `artifact_id`, confirmations, `reason` | `artifact show` | artifact id, project id, phase, checksum, retention status | in the business DB transaction before clear marker |

Read commands that produce guard tokens must expose them in `data.guard_tokens`
with names matching the corresponding parser flags. Envelope-level
`meta.source_fingerprint` is an envelope fingerprint and must not be the only
source for command-specific guard tokens.

### Workflow Reset Semantics

`workflow reset` is a destructive recovery command. It must require:

- `--expected-state`
- `--expected-context-fingerprint`
- `--scope`
- `--to-state`
- `--reason`
- confirmation flags
- `--idempotency-key`

The reset response must include affected resources, invalidated artifacts,
preserved artifacts, before/after workflow state, recovery commands, and next
valid commands. Reset scope determines invalidation rules. For example, a reset
to `SETUP_REQUIRED` with `--scope setup,vision` invalidates setup and vision
session state but must explicitly report whether accepted authority, stories,
sprints, and task history are preserved, hidden, or marked stale.

## Output Contracts

JSON is the default output format. Human-readable text may be added through an
explicit format option.

Every command returns a Pydantic-backed envelope:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "errors": [],
  "meta": {
    "schema_version": "agileforge.cli.v1",
    "command": "agileforge vision generate",
    "command_version": "1",
    "agileforge_version": "dev",
    "storage_schema_version": "1",
    "generated_at": "2026-05-15T12:00:00Z",
    "correlation_id": "8f87d14d-7e1c-4e63-b7c2-a1163f9e0b56",
    "source_fingerprint": "sha256:abc123"
  }
}
```

`correlation_id` is generated automatically when not supplied. Agents may pass
`--correlation-id` to tie retries and multi-command workflows together.
Agents must pass `--idempotency-key` for non-dry-run mutation commands; the
idempotency key is stored in the mutation ledger rather than envelope metadata.

Each command data payload has a named schema, for example:

```text
ProjectCreateResult
ProjectDeleteResult
WorkflowResetResult
AuthorityCompileResult
AuthorityAcceptResult
VisionDraftResult
VisionSaveResult
BacklogDraftResult
RoadmapDraftResult
StoryDraftResult
StoryCloseResult
SprintDraftResult
SprintStartResult
SprintCloseResult
TaskLogResult
ArtifactClearResult
```

Mutation and preview payloads also include the appropriate fields from this set:

```text
before
after
next_actions
mutation_event_id
dry_run
dry_run_id
preview_available
idempotency_key
```

Non-dry-run mutation responses include `mutation_event_id` and
`idempotency_key`. Dry-run preview responses include `dry_run: true`,
`dry_run_id` when supplied, and `preview_available`; they do not include a
mutation ledger id.

`next_actions` must be structured, not plain strings:

```json
{
  "command": "agileforge vision draft save",
  "required_args": {
    "project_id": 1,
    "attempt_id": 12,
    "expected_state": "VISION_REVIEW"
  },
  "guard_token_sources": [
    "agileforge vision draft show --project-id 1 --attempt-id 12",
    "agileforge authority status --project-id 1"
  ],
  "reason": "Save the reviewed vision draft."
}
```

Errors are structured:

```json
{
  "code": "STALE_CONTEXT",
  "message": "Project state changed since the draft was reviewed.",
  "remediation": [
    "agileforge status --project-id 1",
    "agileforge vision draft show --project-id 1 --attempt-id 12"
  ]
}
```

Error codes must come from a central registry. The registry defines the stable
code, default exit code, retryability, and description. Minimum required codes
include `INVALID_COMMAND`, `COMMAND_EXCEPTION`, `COMMAND_NOT_IMPLEMENTED`,
`SCHEMA_NOT_READY`, `SCHEMA_VERSION_MISMATCH`, `PROJECT_NOT_FOUND`,
`AUTHORITY_NOT_ACCEPTED`, `STALE_STATE`, `STALE_ARTIFACT_FINGERPRINT`,
`STALE_CONTEXT_FINGERPRINT`, `STALE_AUTHORITY_VERSION`,
`IDEMPOTENCY_KEY_REUSED`, `MUTATION_RECOVERY_REQUIRED`,
`CONFIRMATION_REQUIRED`, `ACTIVE_STATE_BLOCKS_DELETE`, `MUTATION_FAILED`, and
`MUTATION_ROLLBACK`.

Exit codes must be stable and documented:

- `0`: command succeeded
- `1`: command failed with a runtime error
- `2`: invalid arguments or validation failure
- `3`: stale context or expected-state mismatch
- `4`: workflow or authority guard blocked the command
- `5`: missing schema/storage capability

`storage_schema_version` must be stored in the business database through an
explicit migration/version table. `schema check` compares the required version,
business database version, required tables/columns/indexes, and workflow session
store readiness. Workflow session readiness checks must include configured
storage location, file or database reachability, required ADK session tables,
readable and writable mode for mutation-capable commands, and migration
compatibility. If the ADK session store has no native schema-version source,
`schema check` reports `version_source: unavailable` for that store and relies
on required table/index/read-write checks. Commands that require a newer storage
schema fail before domain reads or writes.

## Implementation Phases

### Phase 2A: CLI Contract Hardening

- envelope metadata enrichment
- central error code registry
- command registry enrichment with command versions and stability status
- storage schema version table and compatibility checks
- `doctor`
- `schema check`
- `capabilities`
- `command schema`
- `mutation show/list/resume`
- mutation guard helpers
- guard-token provenance declarations per command schema
- mutation ledger with idempotency-key replay semantics
- dry-run envelope support
- audit semantics through the mutation ledger
- destructive command policy helpers
- a fake/test mutation command that proves envelopes, schemas, guard failures,
  dry-run, idempotency replay, request-hash mismatch, and audit finalization
  before any real domain mutation ships
- tests proving existing read commands keep working

### Phase 2B: Project Setup Mutation

- `project create`
- `project setup retry`
- mutation envelope models
- schema/help docs for mutation commands
- caller-cwd-safe spec path resolution
- durable cross-store mutation protocol for product/spec/authority/session
  writes
- pending authority output with no auto-accept and no auto-run vision
- durable recovery protocol instead of rollback-only behavior
- tests proving no FastAPI route imports

### Phase 3: Draft Generation And Manual Save

- `vision generate/draft show/draft save`
- `backlog generate/draft show/draft save`
- `roadmap generate/draft show/draft save`
- stale-context guards for all draft saves
- failure artifact output in envelopes

### Phase 4: Story And Sprint Planning

- `story generate/draft show/draft save/phase-complete`
- `sprint candidates/generate/draft show/draft save/start`
- authority and fingerprint guards on story and sprint mutations
- pinned authority evidence in outputs

### Phase 5: Execution Loop

- `story packet`
- `task packet`
- `task history`
- `task log`
- `story close-readiness`
- `story close`
- `sprint close`
- execution history and before/after summaries

### Phase 6: Admin And Recovery

- `project delete`
- `workflow reset`
- `artifact clear`
- soft-delete columns, migrations, and read-projection filtering
- retry, regenerate, and abandon-draft commands
- audit output for destructive actions

## Testing Strategy

Each phase must include:

- unit tests for facade methods
- unit tests for use case services
- CLI transport tests
- JSON envelope and Pydantic schema tests
- guardrail failure tests
- stale-context tests
- dry-run tests
- idempotency replay and request-hash mismatch tests
- mutation ledger/audit finalization tests
- error registry and exit-code tests
- command schema tests for input and output contracts
- guard-token producer/consumer coverage tests
- contract metadata tests for command version, AgileForge version, storage
  schema version, and correlation id
- existing read-command fixture updates when the envelope contract changes
- integration tests over temporary business and session stores
- partial-failure tests for cross-store mutations
- fake/test mutation harness coverage before first real domain mutation
- soft-delete visibility tests when destructive project operations are added
- runtime import boundary tests proving CLI commands do not import FastAPI
  route handlers
- tests proving commands work from outside the AgileForge repository

## Acceptance Criteria

- Agents can discover available commands and schemas through the CLI.
- Agents can create and advance projects without MCP, browser usage, or a
  running web server.
- Query commands remain read-only.
- Generate commands create drafts, not canonical state.
- Canonical mutations require reviewed artifact identity and expected state.
- Canonical mutations reject stale artifact, context, or authority inputs.
- Every non-dry-run mutation requires an idempotency key and supports
  deterministic replay or recovery.
- Cross-store mutations leave a durable recovery record if all declared writes
  do not complete.
- Command schemas declare exact guard-token producers and fingerprint payloads.
- Destructive commands require explicit confirmation flags and a reason.
- Destructive project deletion is recoverable by default.
- Mutation commands support dry-run previews.
- Mutations write durable ledger/audit records with correlation ids.
- CLI outputs are stable, typed, JSON-default envelopes.
- CLI command schemas expose both input and output contracts.
- `next_actions` are structured action objects.
- Schema compatibility checks cover business storage and workflow session
  readiness.
- File path arguments work correctly from arbitrary caller directories.
- The implementation can proceed phase by phase without duplicating workflow
  rules in `cli/main.py`.
