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
- Destructive commands are available by default, but require explicit
  confirmation flags.
- Contract hardening is the next slice before broad lifecycle mutations.
- Mutation guards use explicit expected values rather than one ambiguous
  fingerprint.

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
guard policy, and a transaction policy before it is exposed in the parser.

The standard mutation flow is:

```text
parse args
-> build typed request
-> resolve caller-relative paths
-> load current project/workflow/authority context
-> run guard checks
-> execute use case service
-> write audit event
-> return typed mutation envelope
```

The CLI must support `--dry-run` for mutation commands. A dry run validates the
request and guard checks, returns the current before snapshot and predicted
changes where they can be computed deterministically, and performs no writes.

Each mutation use case must document its write boundary. Business database
writes and workflow session writes may not share one SQLite transaction in the
current architecture. Until that changes, cross-store mutations must use
preflight validation, narrow write ordering, rollback or compensation where
possible, and explicit partial-failure remediation. A command must not claim
atomicity across stores unless tests prove it.

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
agileforge schema ...
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
agileforge project create --name "Project" --spec-file specs/app.md
agileforge project setup retry --project-id 1 --spec-file specs/app.md
agileforge project delete --project-id 1 --confirm-project-id 1 --confirm-project-name "Project" --reason "duplicate project"
```

`project create` initializes the project, links and compiles the specification,
initializes workflow state, and returns the next valid commands. It does not
require a running web server.

`project delete` is a recoverable soft delete in the CLI roadmap. Irreversible
purge requires a separate command and a later, stricter design.

### Workflow Commands

```bash
agileforge workflow state --project-id 1
agileforge workflow next --project-id 1
agileforge workflow reset --project-id 1 --to-state SETUP_REQUIRED --reason "bad setup input" --confirm-project-id 1
```

Workflow reset is available by default, but it requires explicit target state,
reason, and confirmation flags.

### Authority Commands

```bash
agileforge authority status --project-id 1
agileforge authority invariants --project-id 1
agileforge authority compile --project-id 1 --spec-file specs/app.md
agileforge authority show --project-id 1 --spec-version-id 3
agileforge authority accept --project-id 1 --spec-version-id 3 --expected-artifact-fingerprint abc123
```

Authority compilation creates reviewable authority output. Accepting authority
is an explicit canonical mutation.

### Vision, Backlog, And Roadmap Commands

```bash
agileforge vision generate --project-id 1 --input "optional guidance"
agileforge vision draft show --project-id 1 --attempt-id 12
agileforge vision draft save --project-id 1 --attempt-id 12 --expected-state VISION_REVIEW --expected-artifact-fingerprint abc123 --expected-authority-version 3

agileforge backlog generate --project-id 1
agileforge backlog draft show --project-id 1 --attempt-id 13
agileforge backlog draft save --project-id 1 --attempt-id 13 --expected-state BACKLOG_REVIEW --expected-artifact-fingerprint def456 --expected-authority-version 3

agileforge roadmap generate --project-id 1
agileforge roadmap draft show --project-id 1 --attempt-id 14
agileforge roadmap draft save --project-id 1 --attempt-id 14 --expected-state ROADMAP_REVIEW --expected-artifact-fingerprint ghi789 --expected-authority-version 3
```

These phases always generate drafts first. Saving a draft requires a reviewed
attempt id and stale-context guard.

### Story Commands

```bash
agileforge story generate --project-id 1 --requirement "checkout as guest"
agileforge story draft show --project-id 1 --attempt-id 15
agileforge story draft save --project-id 1 --attempt-id 15 --expected-state STORY_REVIEW --expected-artifact-fingerprint jkl012 --expected-authority-version 3
agileforge story show --story-id 7
agileforge story packet --project-id 1 --sprint-id 3 --story-id 7 --flavor agent
agileforge story close-readiness --project-id 1 --sprint-id 3 --story-id 7
agileforge story close --project-id 1 --sprint-id 3 --story-id 7 --expected-context-fingerprint mno345
agileforge story phase-complete --project-id 1 --expected-state STORY_REVIEW
```

Story commands must preserve authority pinning and validation evidence. Closing
a story must verify task state, sprint membership, and review readiness.

### Sprint Commands

```bash
agileforge sprint candidates --project-id 1
agileforge sprint generate --project-id 1 --selected-story-ids 1,2,3
agileforge sprint draft show --project-id 1 --attempt-id 20
agileforge sprint draft save --project-id 1 --attempt-id 20 --team-name "Core" --start-date 2026-05-18 --expected-state SPRINT_REVIEW --expected-artifact-fingerprint pqr678 --expected-authority-version 3
agileforge sprint start --project-id 1 --sprint-id 3 --expected-state SPRINT_PLANNED
agileforge sprint close --project-id 1 --sprint-id 3 --expected-state SPRINT_ACTIVE --expected-context-fingerprint stu901
```

Sprint save and start are canonical mutations. They must fail if the selected
stories, authority status, or workflow state changed after review.

### Task Commands

```bash
agileforge task packet --project-id 1 --sprint-id 3 --task-id 9 --flavor agent
agileforge task history --project-id 1 --sprint-id 3 --task-id 9
agileforge task log --project-id 1 --sprint-id 3 --task-id 9 --expected-status "To Do" --status "In Progress" --changed-by agent
```

Task logging is a canonical execution mutation. It requires the expected prior
task status to prevent stale progress updates.

### Artifact And Schema Commands

```bash
agileforge artifact list --project-id 1
agileforge artifact show --project-id 1 --artifact-id 44
agileforge artifact clear --project-id 1 --artifact-id 44 --confirm-artifact-id 44 --reason "obsolete failed run"

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
```

`doctor` reports runtime health: database reachability, storage schema
readiness, central repo resolution, caller cwd, configured model providers, and
session store reachability.

`capabilities` reports installed commands, command versions, stability,
mutation support, and supported storage/schema versions.

`command schema` returns both input argument schema and output envelope schema
for the named command.

## Guardrails

Read commands must remain read-only. They may detect missing, stale, or invalid
state, but they must not compile specs, repair authority, hydrate mutable
session state, or write to the database.

Draft commands may create attempt records and failure artifacts. They must not
replace accepted/canonical phase output.

Canonical mutations must require the reviewed artifact identity and enough
expected state to fail closed when stale:

- `--attempt-id`, `--draft-id`, `--sprint-id`, `--story-id`, or `--artifact-id`
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

Mutation payloads also include:

```text
before
after
next_actions
audit_event_id
dry_run
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
`CONFIRMATION_REQUIRED`, `ACTIVE_STATE_BLOCKS_DELETE`, `MUTATION_FAILED`, and
`MUTATION_ROLLBACK`.

Exit codes must be stable and documented:

- `0`: command succeeded
- `1`: command failed with a runtime error
- `2`: invalid arguments or validation failure
- `3`: stale context or expected-state mismatch
- `4`: workflow or authority guard blocked the command
- `5`: missing schema/storage capability

## Implementation Phases

### Phase 2A: CLI Contract Hardening

- envelope metadata enrichment
- central error code registry
- command registry enrichment with command versions and stability status
- `doctor`
- `schema check`
- `capabilities`
- `command schema`
- mutation guard helpers
- dry-run envelope support
- audit event model and writer
- destructive command policy helpers
- tests proving existing read commands keep working

### Phase 2B: Project Setup Mutation

- `project create`
- `project setup retry`
- mutation envelope models
- schema/help docs for mutation commands
- caller-cwd-safe spec path resolution
- application-level rollback or explicit partial-failure remediation
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
- audit event tests
- error registry and exit-code tests
- command schema tests for input and output contracts
- contract metadata tests for command version, AgileForge version, storage
  schema version, and correlation id
- integration tests over temporary business and session stores
- partial-failure tests for cross-store mutations
- soft-delete visibility tests for destructive project operations
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
- Destructive commands require explicit confirmation flags and a reason.
- Destructive project deletion is recoverable by default.
- Mutation commands support dry-run previews.
- Mutations write audit events with correlation ids.
- CLI outputs are stable, typed, JSON-default envelopes.
- CLI command schemas expose both input and output contracts.
- File path arguments work correctly from arbitrary caller directories.
- The implementation can proceed phase by phase without duplicating workflow
  rules in `cli/main.py`.
