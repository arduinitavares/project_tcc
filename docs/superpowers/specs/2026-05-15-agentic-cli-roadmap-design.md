# Agentic CLI Roadmap Design

**Date:** 2026-05-15
**Status:** Approved for specification review
**Scope:** Full `agileforge` CLI roadmap for autonomous agents

## Summary

AgileForge needs a complete CLI-first agent interface. Agents should be able to
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

Agents should not be sent through the dashboard or FastAPI as a workaround.
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

## Architecture

The CLI transport should stay thin:

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

Each new mutating command should first promote its business operation into a
focused use case service or facade method. For example, `project create` should
move project creation and setup orchestration behind the application boundary.
The CLI calls that boundary directly. The API can later call the same boundary
where parity is useful.

This keeps the CLI and API as peers over shared application behavior while
avoiding a large rewrite of `api.py`.

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
agileforge project delete --project-id 1 --confirm-project-name "Project"
```

`project create` initializes the project, links and compiles the specification,
initializes workflow state, and returns the next valid commands. It does not
require a running web server.

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
agileforge authority accept --project-id 1 --spec-version-id 3 --expected-fingerprint abc123
```

Authority compilation creates reviewable authority output. Accepting authority
is an explicit canonical mutation.

### Vision, Backlog, And Roadmap Commands

```bash
agileforge vision generate --project-id 1 --input "optional guidance"
agileforge vision draft show --project-id 1 --attempt-id 12
agileforge vision draft save --project-id 1 --attempt-id 12 --expected-state VISION_REVIEW --expected-fingerprint abc123

agileforge backlog generate --project-id 1
agileforge backlog draft show --project-id 1 --attempt-id 13
agileforge backlog draft save --project-id 1 --attempt-id 13 --expected-state BACKLOG_REVIEW --expected-fingerprint def456

agileforge roadmap generate --project-id 1
agileforge roadmap draft show --project-id 1 --attempt-id 14
agileforge roadmap draft save --project-id 1 --attempt-id 14 --expected-state ROADMAP_REVIEW --expected-fingerprint ghi789
```

These phases always generate drafts first. Saving a draft requires a reviewed
attempt id and stale-context guard.

### Story Commands

```bash
agileforge story generate --project-id 1 --requirement "checkout as guest"
agileforge story draft show --project-id 1 --attempt-id 15
agileforge story draft save --project-id 1 --attempt-id 15 --expected-state STORY_REVIEW --expected-fingerprint jkl012
agileforge story show --story-id 7
agileforge story packet --project-id 1 --sprint-id 3 --story-id 7 --flavor agent
agileforge story close-readiness --project-id 1 --sprint-id 3 --story-id 7
agileforge story close --project-id 1 --sprint-id 3 --story-id 7 --expected-fingerprint mno345
agileforge story phase-complete --project-id 1 --expected-state STORY_REVIEW
```

Story commands must preserve authority pinning and validation evidence. Closing
a story must verify task state, sprint membership, and review readiness.

### Sprint Commands

```bash
agileforge sprint candidates --project-id 1
agileforge sprint generate --project-id 1 --selected-story-ids 1,2,3
agileforge sprint draft show --project-id 1 --attempt-id 20
agileforge sprint draft save --project-id 1 --attempt-id 20 --team-name "Core" --start-date 2026-05-18 --expected-state SPRINT_REVIEW --expected-fingerprint pqr678
agileforge sprint start --project-id 1 --sprint-id 3 --expected-state SPRINT_PLANNED
agileforge sprint close --project-id 1 --sprint-id 3 --expected-state SPRINT_ACTIVE --expected-fingerprint stu901
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
- `--expected-fingerprint` or `--expected-authority-version` when reviewed
  content or Spec Authority matters
- phase-specific expected values such as `--expected-status`

If the current state does not match the expected state, the command returns a
typed stale-context error and remediation commands.

Destructive commands must require explicit confirmation flags. The CLI must not
prompt interactively by default because agents need deterministic behavior.
Missing confirmation flags produce structured errors with the required flags.

All canonical and destructive mutations must return before/after summaries
and enough audit metadata to explain what changed and why.

## Output Contracts

JSON is the default output format. Human-readable text may be added through an
explicit format option.

Every command returns a Pydantic-backed envelope:

```json
{
  "ok": true,
  "command": "agileforge vision generate",
  "data": {},
  "warnings": [],
  "errors": [],
  "metadata": {
    "schema_version": "1.0",
    "source_fingerprint": "abc123"
  }
}
```

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

Exit codes must be stable and documented:

- `0`: command succeeded
- `1`: command failed with a runtime error
- `2`: invalid arguments or validation failure
- `3`: stale context or expected-state mismatch
- `4`: workflow or authority guard blocked the command
- `5`: missing schema/storage capability

## Implementation Phases

### Phase 2: Project Setup Mutation

- `project create`
- `project setup retry`
- mutation envelope models
- schema/help docs for mutation commands
- caller-cwd-safe spec path resolution
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
- integration tests over temporary business and session stores
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
- Destructive commands require explicit confirmation flags.
- CLI outputs are stable, typed, JSON-default envelopes.
- File path arguments work correctly from arbitrary caller directories.
- The implementation can proceed phase by phase without duplicating workflow
  rules in `cli/main.py`.
