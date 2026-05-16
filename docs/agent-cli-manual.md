# AgileForge Agent CLI Manual

This manual is the operational reference for agents using the `agileforge`
command-line interface. It is written for agent skill authors and automation
authors who need deterministic command contracts, recovery rules, and safe
workflow sequencing.

The CLI is JSON-first. Agents should parse JSON envelopes, inspect error codes,
and follow explicit remediation and `next_actions` fields. Do not scrape human
help text when a JSON command or schema is available.

## Current Scope

The installed CLI supports:

- Project inspection.
- Project creation with a guarded mutation ledger.
- Project setup retry for interrupted creation/setup recovery.
- Workflow and status inspection.
- Spec Authority status and invariant inspection.
- Story and sprint read projections.
- Bounded context packs for agents.
- CLI diagnostics, schema readiness, command discovery, and command schemas.
- Mutation ledger inspection and recovery lease acquisition.

The installed CLI does not yet support:

- Accepting a pending Spec Authority from the CLI.
- Generating or saving vision, backlog, roadmap, story, or sprint drafts.
- Starting, logging, closing, deleting, or resetting workflow artifacts from the
  CLI.

Agents must not invent unavailable commands. Always confirm command availability
with:

```sh
agileforge capabilities
agileforge command schema "agileforge project create"
```

## Mental Model

AgileForge stores canonical agile workflow state in the central AgileForge
repository. The CLI is the agent-facing transport over that state. Agents call
the CLI from any project directory, but AgileForge internals still resolve from
the central repository.

The CLI has two broad classes of commands:

- Read-only projections: inspect state and return guard tokens.
- Mutations: create or repair canonical state through idempotent commands.

Mutations are guarded by a mutation ledger. The ledger records command identity,
idempotency key, request hash, project id where known, progress steps, status,
stored response, and recovery metadata. This exists so agents can safely retry
after timeouts, crashes, interrupted setup, and stale reads.

Manual checkpoints are a core policy. Generated or compiled artifacts do not
automatically become accepted canonical authority unless an explicit installed
command says so. At the current phase, `project create` compiles a pending
authority artifact, but it does not accept it.

## Central Shim Usage

The intended machine-level executable is:

```sh
~/.local/bin/agileforge
```

The shim should run the central AgileForge repository through `uv`:

```sh
#!/bin/sh
exec uv run --project /Users/aaat/projects/agileforge python -m cli.main "$@"
```

This design means:

- Agents can call `agileforge` from any caller repository.
- Relative user inputs such as `--spec-file specs/app.md` resolve relative to
  the caller's current working directory.
- AgileForge code, dependencies, `.env`, and storage settings resolve through
  the central repository.
- Agents do not need to install AgileForge into every project.

Confirm the shim:

```sh
command -v agileforge
agileforge --help
```

Confirm caller-relative file behavior from another repository:

```sh
cd /path/to/caller-project
agileforge project create --dry-run \
  --dry-run-id preview-project-001 \
  --name "Preview Project" \
  --spec-file specs/app.md
```

## Environment Expectations

The CLI reads AgileForge configuration from the central repo runtime. The usual
environment variables are:

- `OPEN_ROUTER_API_KEY`
- `AGILEFORGE_DB_URL`
- `AGILEFORGE_SESSION_DB_URL`

Run diagnostics before mutation-heavy work:

```sh
agileforge doctor
agileforge schema check
```

`doctor` checks runtime readiness. `schema check` verifies storage readiness for
the CLI contract. If either command returns `ok: false`, agents should stop and
surface the structured error.

## JSON Envelope Contract

Every command returns one JSON envelope on stdout.

Success shape:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "errors": [],
  "meta": {
    "schema_version": "agileforge.cli.v1",
    "command": "agileforge project list",
    "command_version": "1",
    "agileforge_version": "0.1.0",
    "storage_schema_version": "2",
    "generated_at": "2026-05-16T17:20:12Z",
    "correlation_id": "69767371-fd30-4bf3-861e-a83e9127d5e7"
  }
}
```

Failure shape:

```json
{
  "ok": false,
  "data": null,
  "warnings": [],
  "errors": [
    {
      "code": "SPEC_FILE_NOT_FOUND",
      "message": "The requested spec file was not found.",
      "details": {
        "spec_file": "specs/app.md"
      },
      "remediation": [
        "Create the spec file or pass the correct caller-relative path."
      ],
      "exit_code": 2,
      "retryable": false
    }
  ],
  "meta": {
    "schema_version": "agileforge.cli.v1",
    "command": "agileforge project create",
    "command_version": "1",
    "agileforge_version": "0.1.0",
    "storage_schema_version": "2",
    "generated_at": "2026-05-16T17:20:12Z",
    "correlation_id": "69767371-fd30-4bf3-861e-a83e9127d5e7"
  }
}
```

Agent rules:

- Always parse stdout as JSON.
- Treat `ok` as the primary success indicator.
- On `ok: false`, read the first error code and remediation.
- Do not assume `data` is present when `ok` is false. Some recovery errors
  include useful `data`, but not all errors do.
- Preserve `meta.correlation_id` in logs.
- Treat `meta.command_version` and `meta.schema_version` as compatibility
  inputs for agent skills.
- Do not parse stderr for command results. Logging should not be part of the
  data contract.

Python parser pattern:

```sh
payload="$(agileforge status --project-id 1)"
PAYLOAD="$payload" python - <<'PY'
import json
import os
import sys

envelope = json.loads(os.environ["PAYLOAD"])
if not envelope["ok"]:
    error = envelope["errors"][0]
    print(error["code"], file=sys.stderr)
    print(error.get("remediation", []), file=sys.stderr)
    raise SystemExit(error.get("exit_code", 1))

print(envelope["data"])
PY
```

## Command Discovery

Start with capabilities:

```sh
agileforge capabilities
```

This returns installed command metadata:

- `name`
- `phase`
- `mutates`
- `stable`
- `destructive`
- accepted guard fields
- idempotency policy
- required and optional inputs
- possible error codes

Inspect one command contract:

```sh
agileforge command schema "agileforge project create"
```

Use `command schema` before writing an agent skill workflow. It gives the
machine-readable command contract, including:

- required input fields
- optional input fields
- whether the command mutates state
- whether idempotency is required
- guard policy
- documented error codes
- exit codes
- envelope schema

List available command names:

```sh
agileforge capabilities | python -c 'import json,sys; p=json.load(sys.stdin); print("\n".join(c["name"] for c in p["data"]["commands"]))'
```

## Installed Command Reference

### Operational Commands

```sh
agileforge doctor
agileforge schema check
agileforge capabilities
agileforge command schema "agileforge project create"
```

Use these before and during agent workflows.

### Project Commands

```sh
agileforge project list
agileforge project show --project-id 1
agileforge project create --name "Project" --spec-file specs/app.md --idempotency-key create-project-001
agileforge project create --dry-run --dry-run-id preview-project-001 --name "Project" --spec-file specs/app.md
agileforge project setup retry --project-id 1 --spec-file specs/app.md --expected-state SETUP_REQUIRED --expected-context-fingerprint sha256:... --recovery-mutation-event-id 10 --idempotency-key setup-retry-001
```

`project create` and `project setup retry` mutate state.

### Workflow Commands

```sh
agileforge workflow state --project-id 1
agileforge workflow next --project-id 1
```

Use `workflow state` for current FSM/session state and `workflow next` for
installed next commands.

### Authority Commands

```sh
agileforge authority status --project-id 1
agileforge authority invariants --project-id 1
agileforge authority invariants --project-id 1 --spec-version-id 3
```

At the current phase, authority commands are read-only. A project created from
the CLI should show `status: pending_acceptance`, `authority_id: null`, and a
populated `pending_authority_id`.

### Story Commands

```sh
agileforge story show --story-id 42
```

Read-only.

### Sprint Commands

```sh
agileforge sprint candidates --project-id 1
```

Read-only.

### Context Commands

```sh
agileforge context pack --project-id 1 --phase overview
agileforge context pack --project-id 1 --phase sprint-planning
```

Use context packs to get bounded agent context and guard tokens.

### Status Command

```sh
agileforge status --project-id 1
```

Use this for quick project orientation.

### Mutation Ledger Commands

```sh
agileforge mutation list
agileforge mutation list --project-id 1
agileforge mutation list --project-id 1 --status recovery_required
agileforge mutation show --mutation-event-id 10
agileforge mutation resume --mutation-event-id 10
```

`mutation show` and `mutation list` are read-only. `mutation resume` is a
mutating operational command that acquires a recovery lease on a
recovery-required mutation. At the current phase, domain-specific project setup
repair should normally use `project setup retry`; use `mutation resume` only
when the returned remediation tells you to inspect or acquire recovery.

## Idempotency Keys

Domain mutations require `--idempotency-key` for non-dry-run execution.

Installed domain mutations:

- `agileforge project create`
- `agileforge project setup retry`

For `project create` and `project setup retry`, the parser enforces:

- non-dry-run mutations require `--idempotency-key`
- dry-runs forbid `--idempotency-key`
- dry-runs require `--dry-run-id`

Token rules for `idempotency_key` and `dry_run_id`:

- ASCII only
- 8 to 128 characters
- allowed characters: `A-Z`, `a-z`, `0-9`, `.`, `_`, `:`, `-`

Good keys:

```text
create-cartola-20260516-001
setup-retry-project-12-001
agent:project-create:cartola:001
```

Bad keys:

```text
short
contains spaces
contains/slashes
contains-non-ascii
```

Idempotency behavior:

- Same command, same key, same canonical request: replay the stored response.
- Same command, same key, different canonical request: return
  `IDEMPOTENCY_KEY_REUSED`.
- Different command can use its own key namespace, but agent skills should still
  make keys globally descriptive.
- If the agent times out after submitting a mutation, retry the exact same
  command with the same idempotency key before creating a new attempt.

The canonical request hash includes normalized inputs such as resolved spec path,
spec hash, stale guards, recovery link, and `changed_by` where relevant. It does
not include `correlation_id`.

`agileforge mutation resume` is also mutating, but it is an operational recovery
command over an existing ledger row. It does not accept an idempotency key
because the mutation event id is the identity of the recovery target.

## Correlation IDs and Changed By

Mutating commands accept:

```sh
--correlation-id CORRELATION_ID
--changed-by CHANGED_BY
```

Use `--correlation-id` to connect logs across a larger agent run. If omitted,
the CLI generates one.

Use `--changed-by` to identify the actor in the mutation ledger. If omitted,
the default is:

```text
cli-agent
```

Recommended agent values:

```text
codex
claude
cursor-agent
ci-agent
```

Keep `changed_by` stable for a run. Changing `changed_by` on an idempotent retry
can change the canonical request hash for some commands and trigger
`IDEMPOTENCY_KEY_REUSED`.

## Dry-Run Semantics

Dry-runs validate inputs and preview deterministic command behavior without
creating mutation ledger rows and without writing domain state.

For `project create`:

```sh
agileforge project create \
  --dry-run \
  --dry-run-id preview-cartola-001 \
  --name "caRtola" \
  --spec-file specs/app.md
```

Expected success data includes:

- `preview_available: true`
- `name`
- `resolved_spec_path`

For `project setup retry`:

```sh
agileforge project setup retry \
  --dry-run \
  --dry-run-id preview-setup-retry-001 \
  --project-id 1 \
  --spec-file specs/app.md \
  --expected-state SETUP_REQUIRED \
  --expected-context-fingerprint sha256:... \
  --recovery-mutation-event-id 10
```

Dry-run rules:

- Do not pass `--idempotency-key` with `--dry-run`.
- Always pass `--dry-run-id`.
- Do not treat dry-run success as proof the real command will succeed later.
  State may change between preview and execution.
- A dry-run does not consume an idempotency key.
- A dry-run does not acquire recovery leases.
- A dry-run does not update existing recovery ledger rows.

## Creating a Project

Project creation is the first installed canonical mutation flow.

It does all of the following:

1. Resolves the spec file relative to the caller current working directory.
2. Validates the spec file exists and is readable.
3. Creates a `Product`.
4. Persists a `SpecRegistry` version.
5. Compiles a pending `CompiledSpecAuthority`.
6. Initializes or reconciles workflow session setup state.
7. Finalizes the mutation ledger response.

It does not create a `SpecAuthorityAcceptance` row.

### Recommended Agent Flow

From the caller project:

```sh
cd /path/to/caller-project
test -f specs/app.md
```

Preview:

```sh
agileforge project create \
  --dry-run \
  --dry-run-id preview-cartola-001 \
  --name "caRtola" \
  --spec-file specs/app.md
```

Execute:

```sh
agileforge project create \
  --name "caRtola" \
  --spec-file specs/app.md \
  --idempotency-key create-cartola-20260516-001 \
  --changed-by codex
```

Parse project id:

```sh
payload="$(agileforge project create \
  --name "caRtola" \
  --spec-file specs/app.md \
  --idempotency-key create-cartola-20260516-001 \
  --changed-by codex)"

PROJECT_ID="$(
  PAYLOAD="$payload" python -c 'import json,os; p=json.loads(os.environ["PAYLOAD"]); print(p["data"]["project_id"] if p["ok"] else "")'
)"
```

Inspect status:

```sh
agileforge status --project-id "$PROJECT_ID"
agileforge workflow state --project-id "$PROJECT_ID"
agileforge authority status --project-id "$PROJECT_ID"
```

Project-create success data uses the same authority naming policy as
`authority status`:

- `authority_id` is the accepted authority id and remains `null` after project
  creation.
- `pending_authority_id` is the compiled authority awaiting review.
- `compiled_authority_id` is an alias for the compiled pending authority created
  by setup.
- `pending_compiled_spec_version_id` is the spec version used to compile the
  pending authority.

Expected authority state immediately after successful project creation:

```json
{
  "status": "pending_acceptance",
  "authority_id": null,
  "pending_authority_id": 3,
  "pending_compiled_spec_version_id": 3,
  "pending_authority_fingerprint": "sha256:..."
}
```

Agent stop rule:

- If authority is pending, stop and report the project id and pending authority
  details.
- Do not attempt `agileforge authority accept`; it is not installed yet.
- Do not use direct SQLite edits or HTTP calls to accept authority.

## Reading Pending Authority

Use:

```sh
agileforge authority status --project-id "$PROJECT_ID"
```

Important fields:

- `status`: high-level authority status.
- `latest_spec_version_id`: latest spec row for the project.
- `accepted_spec_version_id`: accepted spec version if any.
- `accepted_decision_id`: accepted decision if any.
- `authority_id`: accepted/current authority id only.
- `pending_authority_id`: compiled but unaccepted authority id.
- `pending_compiled_spec_version_id`: spec version for pending authority.
- `pending_compiled_at`: timestamp for pending compilation.
- `pending_compiler_version`: compiler version.
- `pending_prompt_hash`: prompt hash for pending compilation.
- `pending_invariant_count`: parsed invariant count for pending authority.
- `pending_authority_fingerprint`: review token for the pending authority.
- `authority_fingerprint`: projection fingerprint for authority status.
- `disk_spec`: resolved disk spec path and hash information.

Read invariants:

```sh
agileforge authority invariants --project-id "$PROJECT_ID"
```

If no authority is accepted, invariant output may return an authority-related
error. Agents should surface that status rather than forcing progress.

## Guard Tokens

Guard tokens prevent agents from mutating stale state.

Current installed guard-bearing command:

```sh
agileforge project setup retry
```

Required guards:

- `--expected-state`
- `--expected-context-fingerprint`

Get current state:

```sh
agileforge workflow state --project-id "$PROJECT_ID"
```

Get context fingerprint:

```sh
agileforge context pack --project-id "$PROJECT_ID" --phase overview
```

Extract `expected_context_fingerprint`:

```sh
CTX="$(
  agileforge context pack --project-id "$PROJECT_ID" --phase overview |
  python -c 'import json,sys; print(json.load(sys.stdin)["data"]["guard_tokens"]["expected_context_fingerprint"])'
)"
```

If a guarded command returns `STALE_STATE` or `STALE_CONTEXT_FINGERPRINT`, do not
retry blindly. Refresh `workflow state` and `context pack`, review the new
state, and then issue a new command with a new idempotency key.

## Mutation Ledger

The mutation ledger is the source of truth for mutation attempts and recovery.

List all mutation events:

```sh
agileforge mutation list
```

List project-specific events:

```sh
agileforge mutation list --project-id "$PROJECT_ID"
```

List recovery-required events:

```sh
agileforge mutation list --project-id "$PROJECT_ID" --status recovery_required
```

Show one event:

```sh
agileforge mutation show --mutation-event-id "$MUTATION_EVENT_ID"
```

Common statuses:

- `pending`: a command owns an active lease or may be stale-pending.
- `succeeded`: mutation finalized successfully.
- `guard_rejected`: stale guard or similar precondition blocked mutation.
- `domain_failed_no_side_effects`: request failed before domain writes started.
- `recovery_required`: some durable side effect may need reconciliation.
- `superseded`: an original recovery row was superseded by a linked retry row.

Agent rules:

- If a command returns `MUTATION_IN_PROGRESS`, wait briefly and inspect the
  mutation event before retrying.
- If a command returns `MUTATION_RECOVERY_REQUIRED`, inspect the mutation event
  and follow `data.next_actions` or `errors[0].remediation`.
- If a command returns `IDEMPOTENCY_KEY_REUSED`, do not keep retrying. Generate
  a new idempotency key only after reviewing why the request differs.
- If a command returns `MUTATION_RESUME_CONFLICT`, another worker may have won a
  recovery lease. Re-read the mutation event.

## Project Setup Retry

Use setup retry when `project create` recorded partial setup and returned
`MUTATION_RECOVERY_REQUIRED`.

The retry command can link to the original failed create event:

```sh
agileforge project setup retry \
  --project-id "$PROJECT_ID" \
  --spec-file specs/app.md \
  --expected-state SETUP_REQUIRED \
  --expected-context-fingerprint "$CTX" \
  --recovery-mutation-event-id "$RECOVERY_EVENT_ID" \
  --idempotency-key "setup-retry-$PROJECT_ID-001" \
  --changed-by codex
```

Recommended recovery sequence:

1. Read the original mutation:

   ```sh
   agileforge mutation show --mutation-event-id "$RECOVERY_EVENT_ID"
   ```

2. Confirm project state:

   ```sh
   agileforge workflow state --project-id "$PROJECT_ID"
   agileforge authority status --project-id "$PROJECT_ID"
   ```

3. Get a fresh context fingerprint:

   ```sh
   CTX="$(
     agileforge context pack --project-id "$PROJECT_ID" --phase overview |
     python -c 'import json,sys; print(json.load(sys.stdin)["data"]["guard_tokens"]["expected_context_fingerprint"])'
   )"
   ```

4. Run retry with a new idempotency key:

   ```sh
   agileforge project setup retry \
     --project-id "$PROJECT_ID" \
     --spec-file specs/app.md \
     --expected-state SETUP_REQUIRED \
     --expected-context-fingerprint "$CTX" \
     --recovery-mutation-event-id "$RECOVERY_EVENT_ID" \
     --idempotency-key "setup-retry-$PROJECT_ID-$(date +%Y%m%d%H%M%S)" \
     --changed-by codex
   ```

5. Re-read mutation list:

   ```sh
   agileforge mutation list --project-id "$PROJECT_ID"
   ```

A successful linked retry supersedes the original recovery row. Replaying the
original create idempotency key should return the stored recovery/success
response rather than creating duplicate setup artifacts.

## Mutation Resume

Use:

```sh
agileforge mutation resume --mutation-event-id "$MUTATION_EVENT_ID"
```

This command is an operational recovery command. It mutates only ledger recovery
ownership. It does not accept altered domain arguments from the original command.

Use it when:

- a remediation explicitly tells you to inspect or acquire recovery;
- you need to determine whether recovery is still owned by another worker;
- a stale recovery row needs a lease transition before domain-specific repair.

Do not use it as a replacement for `project setup retry` when the remediation
requires stale guards and a spec file.

## Error Codes

Registered CLI error codes include:

| Code | Meaning | Agent response |
| --- | --- | --- |
| `INVALID_COMMAND` | Parser or flag contract failed. | Fix command syntax. |
| `COMMAND_EXCEPTION` | Unexpected exception. | Surface logs and command envelope. |
| `COMMAND_NOT_IMPLEMENTED` | Command route is not implemented. | Stop using that command. |
| `SCHEMA_NOT_READY` | Storage schema is missing or incompatible. | Run diagnostics, migrate/init storage outside the agent workflow. |
| `PROJECT_NOT_FOUND` | Project id does not exist. | Refresh project list. |
| `PROJECT_ALREADY_EXISTS` | Project name is already used. | Pick a different name or inspect existing project. |
| `STORY_NOT_FOUND` | Story id does not exist. | Refresh story/project state. |
| `SPEC_VERSION_NOT_FOUND` | Spec version does not exist. | Refresh authority status. |
| `SPEC_FILE_NOT_FOUND` | Spec path cannot be found. | Fix caller-relative path. |
| `SPEC_FILE_INVALID` | Spec path exists but is invalid. | Fix spec file content/path. |
| `SPEC_COMPILE_FAILED` | Authority compilation failed. | Inspect error details, retry only when cause is fixed. |
| `AUTHORITY_NOT_ACCEPTED` | No accepted authority exists. | Stop or request manual authority review. |
| `AUTHORITY_NOT_COMPILED` | Selected spec has no compiled authority. | Re-read authority status. |
| `AUTHORITY_ACCEPTANCE_MISMATCH` | Accepted authority provenance drifted. | Stop and surface. |
| `AUTHORITY_INVARIANTS_INVALID` | Stored invariant JSON is invalid. | Stop and surface storage issue. |
| `STALE_STATE` | Expected workflow state mismatched. | Refresh state, review, use new key. |
| `STALE_ARTIFACT_FINGERPRINT` | Reviewed artifact changed. | Re-read artifact before mutating. |
| `STALE_CONTEXT_FINGERPRINT` | Reviewed context changed. | Rebuild context pack before retry. |
| `STALE_AUTHORITY_VERSION` | Accepted authority version changed. | Re-read authority before retry. |
| `CONFIRMATION_REQUIRED` | Destructive confirmation missing. | Add required confirmation flags only after review. |
| `ACTIVE_STATE_BLOCKS_DELETE` | Active workflow blocks destructive op. | Stop or complete/reset workflow first. |
| `SCHEMA_VERSION_MISMATCH` | Storage schema version incompatible. | Run schema migration/check outside workflow. |
| `MUTATION_FAILED` | Mutation failed without a more specific code. | Inspect details and mutation ledger. |
| `MUTATION_ROLLBACK` | Mutation rolled back or needs recovery. | Inspect mutation ledger. |
| `MUTATION_IN_PROGRESS` | Active lease exists. | Wait or inspect event. |
| `MUTATION_RECOVERY_REQUIRED` | Durable recovery is required. | Follow `next_actions` and remediation. |
| `MUTATION_RESUME_CONFLICT` | Another worker acquired recovery. | Re-read mutation event. |
| `MUTATION_RECOVERY_INVALID` | Recovery link is invalid. | Refresh mutation list and use correct event id. |
| `IDEMPOTENCY_KEY_REUSED` | Same key used with different request. | Stop and generate a new reviewed attempt. |
| `MUTATION_NOT_FOUND` | Mutation event id does not exist. | Refresh mutation list. |
| `WORKFLOW_SESSION_FAILED` | Workflow session setup failed. | Inspect recovery state and retry setup if directed. |

Agents should use the command-specific schema for exact possible errors:

```sh
agileforge command schema "agileforge project setup retry"
```

## Copy-Paste Recipes

### Health Check

```sh
agileforge doctor
agileforge schema check
agileforge capabilities
```

### Create New Project From Caller Repo

```sh
cd /path/to/caller-project

agileforge project create \
  --dry-run \
  --dry-run-id preview-my-project-001 \
  --name "My Project" \
  --spec-file specs/app.md

payload="$(
  agileforge project create \
    --name "My Project" \
    --spec-file specs/app.md \
    --idempotency-key create-my-project-20260516-001 \
    --changed-by codex
)"

PROJECT_ID="$(
  PAYLOAD="$payload" python -c 'import json,os,sys; p=json.loads(os.environ["PAYLOAD"]); print(p["data"]["project_id"] if p["ok"] else ""); sys.exit(0 if p["ok"] else p["errors"][0].get("exit_code",1))'
)"

agileforge authority status --project-id "$PROJECT_ID"
```

### Inspect Pending Authority

```sh
agileforge authority status --project-id "$PROJECT_ID" |
python -c 'import json,sys; p=json.load(sys.stdin); d=p["data"]; print({"status": d["status"], "authority_id": d["authority_id"], "pending_authority_id": d["pending_authority_id"], "pending_spec": d["pending_compiled_spec_version_id"]})'
```

### Recover Project Setup

```sh
agileforge mutation list --project-id "$PROJECT_ID" --status recovery_required

RECOVERY_EVENT_ID=10

CTX="$(
  agileforge context pack --project-id "$PROJECT_ID" --phase overview |
  python -c 'import json,sys; print(json.load(sys.stdin)["data"]["guard_tokens"]["expected_context_fingerprint"])'
)"

agileforge project setup retry \
  --project-id "$PROJECT_ID" \
  --spec-file specs/app.md \
  --expected-state SETUP_REQUIRED \
  --expected-context-fingerprint "$CTX" \
  --recovery-mutation-event-id "$RECOVERY_EVENT_ID" \
  --idempotency-key "setup-retry-$PROJECT_ID-$(date +%Y%m%d%H%M%S)" \
  --changed-by codex
```

### Replay After Timeout

If a mutation command timed out and the agent does not know whether it succeeded,
run the exact same command again with the exact same idempotency key:

```sh
agileforge project create \
  --name "My Project" \
  --spec-file specs/app.md \
  --idempotency-key create-my-project-20260516-001 \
  --changed-by codex
```

Do not change `--name`, `--spec-file`, `--changed-by`, or the idempotency key
during replay. A different request with the same key returns
`IDEMPOTENCY_KEY_REUSED`.

## Agent Skill Guidance

An AgileForge CLI skill should implement these steps.

### Startup

1. Run `command -v agileforge`.
2. Run `agileforge doctor`.
3. Run `agileforge schema check`.
4. Run `agileforge capabilities`.
5. Cache installed command names and command schemas for the current session.

### Before Any Mutation

1. Confirm command appears in `capabilities`.
2. Read `command schema`.
3. Build request from schema-required fields.
4. Generate a valid idempotency key for non-dry-run mutations.
5. Use `--dry-run` first when the command supports it and deterministic preview
   is useful.
6. For guarded commands, fetch fresh guard tokens immediately before execution.

### After Any Mutation

1. Parse the JSON envelope.
2. If `ok: true`, store `data.mutation_event_id` when present.
3. Follow `data.next_actions` when present.
4. If `ok: false`, branch on `errors[0].code`.
5. For recovery errors, inspect `mutation show` and use exact remediation.
6. Never create a second mutation attempt until idempotency replay and recovery
   state are understood.

### Stop Conditions

The skill must stop and surface state when:

- command is not installed;
- schema is not ready;
- authority is pending and no CLI accept command exists;
- stale guard is returned;
- idempotency key was reused with a different request;
- mutation recovery requires manual inspection;
- direct DB/API/browser use would be needed to continue.

### Do Not

- Do not install AgileForge into each caller repo.
- Do not call FastAPI routes or require a web server for the CLI workflow.
- Do not use browser automation as the agent interface.
- Do not edit SQLite directly.
- Do not treat generated or compiled authority as accepted.
- Do not call roadmap commands that are not installed.
- Do not mutate after a stale guard without refreshing state.
- Do not retry with a changed request and the same idempotency key.

## Roadmap Commands Not Yet Installed

The broader CLI roadmap includes commands such as:

- `agileforge authority accept`
- `agileforge vision generate`
- `agileforge backlog generate`
- `agileforge roadmap generate`
- `agileforge story generate`
- `agileforge sprint generate`
- `agileforge sprint start`
- `agileforge task log`
- `agileforge workflow reset`
- `agileforge project delete`

These are not part of the current installed command set unless they appear in
`agileforge capabilities`. Agent skills must check capabilities at runtime and
must not assume roadmap commands exist.
