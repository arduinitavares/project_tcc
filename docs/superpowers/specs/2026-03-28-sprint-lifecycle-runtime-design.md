# Sprint Lifecycle Runtime and UX Contract Design

**Date:** 2026-03-28
**Status:** Approved for planning
**Scope:** Sprint lifecycle runtime, project-shell UX contract, and backend/frontend alignment

## Summary

The current sprint experience mixes two different concerns:

- one-time project planning progression
- repeatable sprint runtime lifecycle

That coupling creates a misleading user experience after the first sprint is saved or completed. The project sidebar turns fully complete, the project can look permanently "done," and there is no clean product-level path for closing one sprint and intentionally planning the next one.

This design separates those concerns into two stable contracts:

- the project shell tracks planning progression and exposes only a lightweight sprint runtime summary
- the sprint workspace owns the repeatable lifecycle of `Planned -> Active -> Completed` sprints plus sprint history

Under this contract, planning can be complete while sprint runtime continues across multiple iterations.

## Problem Statement

The repository already contains partial support for sprint lifecycle concepts:

- `Sprint.status` supports `Planned`, `Active`, and `Completed`
- workflow events include `SPRINT_STARTED` and `SPRINT_COMPLETED`
- the project UI distinguishes saved sprint plans and started sprints

However, the current product contract is inconsistent:

- the global FSM and sidebar treat sprint completion as a near-terminal project milestone
- the frontend largely infers sprint mode from `started_at` instead of using canonical persisted runtime status
- completed sprint history is not first-class in the workspace contract
- there is no explicit close-sprint flow parallel to the existing manual story-close flow
- the path from "finished current sprint" to "plan next sprint" is not clearly reopened

The result is a design gap: the domain model implies multi-sprint iteration, but the UX still behaves like sprint planning is the end of the project.

## Goals

- Keep the main sidebar focused on one-time planning progression.
- Show a lightweight current sprint runtime summary in the project shell.
- Make persisted sprint records the canonical source of sprint runtime state.
- Support many completed sprints, at most one active sprint, and at most one open planned sprint.
- Make sprint start and sprint close explicit user actions.
- Preserve completed sprints as immutable historical records.
- Allow unfinished stories from completed sprints to become eligible inputs for the next sprint without automatic rollover.
- Expose a server-derived API contract so the frontend stops reconstructing lifecycle rules locally.

## Non-Goals

- Turning the main sidebar into a recurring sprint execution timeline.
- Supporting multiple queued future planned sprints.
- Automatically rolling unfinished stories into the next sprint.
- Rewriting existing historical sprint links or mutating closed sprint scope.
- Designing multi-sprint roadmap queue management in this iteration.

## Design Principles

### 1. Separate Planning from Runtime

The global project shell should answer:

> Has the project completed the planning pipeline, and what is the current sprint situation?

The sprint workspace should answer:

> Which sprint are we looking at, what state is it in, and what can the user do next?

### 2. Persist Runtime State Explicitly

Sprint lifecycle must come from persisted sprint records, not from UI guesses based on one field such as `started_at`.

### 3. Keep History Truthful

A completed sprint should remain a truthful record of what was committed, what finished, and what did not finish at close time.

### 4. Prefer Explicit User Intent

Starting a sprint and closing a sprint are explicit user actions. The system informs the user with readiness data and guardrails, but it does not silently complete or silently roll work forward.

## Canonical Lifecycle Model

This design defines a clean sprint runtime lifecycle:

- `Planned`
- `Active`
- `Completed`

Lifecycle rules:

- a project may have many `Completed` sprints
- a project may have at most one `Active` sprint
- a project may have at most one open `Planned` sprint
- a project may simultaneously have one `Active` sprint and one next `Planned` sprint
- `Planned` means a sprint has been saved and is ready to start
- `Active` means the user explicitly started the sprint
- `Completed` means the user explicitly closed the sprint after a readiness review

Lifecycle transitions:

- `save sprint plan` creates or updates the single open `Planned` sprint, including while another sprint is currently `Active`
- `start sprint` transitions `Planned -> Active`
- `close sprint` transitions `Active -> Completed`

Unsupported transitions:

- `Completed -> Active`
- `Completed -> Planned`
- creating a second planned sprint while one already exists
- starting a sprint while another sprint is already active

## Project Shell UX Contract

The project shell remains a planning-oriented surface. It does not become a repeating sprint execution timeline.

### Sidebar and Stepper

The main sidebar remains a six-step planning tracker:

- setup
- vision
- backlog
- roadmap
- stories
- sprint

The `Sprint` step becomes complete when the project has at least one saved sprint plan. After that point, the project shell communicates:

> Planning is complete. Sprint runtime continues in the sprint workspace.

The shell must not imply that the project itself is permanently finished.

### Lightweight Runtime Summary

The shell should expose a compact sprint runtime summary with states such as:

- `No sprint yet`
- `Planned sprint ready`
- `Sprint active`
- `No active sprint; last sprint completed`

This summary is informational. It is not a repeated stepper or a full sprint history view.

### Overview Panel

The overview splits two concerns:

- `Planning Status`
- `Sprint Runtime`

Primary action priority:

1. Open active sprint
2. Open planned sprint
3. Create next sprint

That priority prevents dead ends and keeps the user focused on the most actionable sprint surface.

## Sprint Workspace UX Contract

The sprint workspace becomes the home for repeatable sprint lifecycle behavior.

### Landing Priority

When the user enters the sprint workspace:

1. if an active sprint exists, land there
2. else if a planned sprint exists, land there
3. else land on the sprint hub/history view with a `Create Next Sprint` action

### Sprint History and Selection

The sprint workspace owns the first-class list/selector for:

- active sprint
- planned sprint
- completed sprint history

Completed sprints remain visible and accessible as history. They are not hidden behind the main sidebar.

### Planned Sprint View

The planned sprint view shows a saved sprint that has not started yet and supports:

- `Start Sprint`
- `Modify Planned Sprint`

Because only one open planned sprint is allowed, users modify the existing planned sprint instead of creating additional queued sprints.

### Active Sprint View

The active sprint view is execution-oriented. It focuses on:

- story progress
- task progress
- story close flow
- a prominent `Close Sprint` action

### Completed Sprint View

The completed sprint view is read-only historical output. It shows:

- original committed scope
- what was completed at close time
- what remained unfinished at close time
- carry-over candidates
- close notes and follow-up notes

The completed sprint record must not silently mutate after closure.

### Close Sprint Flow

Sprint completion follows the existing product pattern of explicit manual close.

`Close Sprint` opens a readiness review with:

- completed stories
- open stories
- unfinished work that could carry over later
- optional close notes
- optional follow-up or rollover notes

The system clearly warns about unfinished work but still allows informed manual closure. It does not require a perfect sprint.

### Post-Close Navigation

After closing a sprint:

- if a planned sprint already exists, route the user there
- otherwise route the user to the completed sprint summary with a clear `Create Next Sprint` action

## Backend State Model Contract

### Canonical Runtime Source

Persisted sprint records are the source of truth for runtime state. The frontend should stop inferring runtime mode from `started_at` alone and instead use canonical sprint payloads from the API.

### Sprint Fields

The sprint model should expose:

- `status`: `Planned | Active | Completed`
- `started_at`
- `completed_at`

The model may also store close metadata directly or through a companion snapshot artifact, but `completed_at` is required so completion is a real persisted state rather than a UI inference.

### Close Snapshot Artifact

Completed sprint views need a truthful historical record, even if linked stories later continue in future sprints. For that reason, sprint close should persist a denormalized close snapshot.

The snapshot should include:

- `closed_at`
- sprint status at close time
- `completed_story_count`
- `open_story_count`
- story summaries at close time
- story title
- story status at close
- task rollups at close
- whether each story was complete or unfinished
- unfinished carry-over candidates
- close notes
- follow-up or rollover notes

The completed sprint view should render from this snapshot when available.

### Snapshot Fidelity for Legacy Records

Older completed sprints may not have a close snapshot. The API should expose history fidelity explicitly so the UI can be honest about legacy records.

Recommended field:

- `history_fidelity`: `"snapshotted"` or `"derived"`

Optional convenience field:

- `close_snapshot_available`: `true` or `false`

This allows the UI to distinguish between:

- fully preserved close-time history
- legacy completed history reconstructed from current linked data

### Runtime Invariants

The backend must enforce lifecycle invariants in write paths, not only in the UI:

- only one active sprint per project
- only one open planned sprint per project
- only active sprints can be closed
- only planned sprints can be started

These rules should be enforced in:

- sprint save/create-next-sprint flows
- start-sprint flow
- close-sprint flow

## Story Eligibility and Rollover Contract

Completed sprints remain immutable. Unfinished work is not moved out of them.

Instead:

- stories already committed to an open `Planned` or `Active` sprint are not eligible sprint candidates
- stories linked only to `Completed` sprints may become eligible again if they remain unfinished
- selecting such a story into the next sprint creates a new sprint-story association rather than moving or rewriting the old one

This preserves truthful history while allowing explicit rollover through the next planning cycle.

## API Contract

The API should provide server-derived lifecycle semantics directly so the frontend stops reconstructing them locally.

### Sprint List Response

`GET /api/projects/{project_id}/sprints` should remain the primary sprint workspace source, but the response should be enriched with:

- canonical `status`
- `started_at`
- `completed_at`
- `history_fidelity`
- allowed actions for each sprint

Recommended allowed-action fields:

- `can_start`
- `can_close`
- `can_modify_planned`

When an action is unavailable, the API should also provide reason strings where useful, for example:

- `start_disabled_reason`
- `close_disabled_reason`
- `modify_disabled_reason`

### Project-Level Runtime Summary

The sprint list response, or a dedicated project runtime summary payload, should include:

- `active_sprint_id`
- `planned_sprint_id`
- `latest_completed_sprint_id`
- whether next-sprint creation is currently allowed

Recommended project-level action fields:

- `can_create_next_sprint`
- `create_next_sprint_disabled_reason`

`can_create_next_sprint` should be derived entirely on the server. It is allowed when there is no open planned sprint, even if an active sprint currently exists.

### Close Sprint Endpoints

Add explicit close endpoints parallel to the existing story-close interaction:

- `GET /api/projects/{project_id}/sprints/{sprint_id}/close`
  Returns readiness preview and close eligibility information.
- `POST /api/projects/{project_id}/sprints/{sprint_id}/close`
  Persists closure, stamps `completed_at`, writes the close snapshot, and returns the completed sprint payload.

## Error Handling Contract

Lifecycle guardrails should surface as specific workflow conflicts:

- `409 Conflict` when starting a sprint while another sprint is active
- `409 Conflict` when creating or saving a new planned sprint while another planned sprint exists
- `409 Conflict` when closing a sprint that is not active
- `404 Not Found` when the sprint does not belong to the project
- `422 Unprocessable Entity` for malformed close payloads

The frontend should render these as actionable guidance rather than generic errors.

## FSM Alignment and Legacy Session Handling

The global FSM should stop implying that sprint completion equals project completion.

Recommended shell behavior:

- `SPRINT_PERSISTENCE` becomes the stable planning-complete project-shell state
- legacy `SPRINT_COMPLETE` sessions should render with the same planning-complete shell semantics

This can be implemented by either:

- normalizing `SPRINT_COMPLETE` to `SPRINT_PERSISTENCE` at the API boundary, or
- treating both as equivalent planning-complete states in shell rendering

The important behavior is that legacy sessions continue to load correctly without making the project appear terminally finished.

## Migration Strategy

Use a minimal-risk migration strategy:

1. add `completed_at` and close snapshot storage
2. keep existing sprint rows valid without rewriting their history
3. begin writing close snapshots for newly closed sprints
4. mark older completed records as `history_fidelity = "derived"` when no snapshot exists

This avoids heavy data rewrites and keeps momentum on the current feature branch.

## Testing Contract

Testing should target lifecycle invariants and contract boundaries, not just visible UI symptoms.

### Backend Tests

- saving a sprint creates or updates the single open planned sprint
- starting a sprint transitions it to `Active`
- starting a sprint is blocked when another sprint is already active
- closing a sprint transitions it to `Completed`
- closing a sprint stamps `completed_at`
- closing a sprint writes a close snapshot
- completed sprints remain listable and readable
- stories in open planned or active sprints are excluded from sprint candidates
- unfinished stories from completed sprints are eligible sprint candidates
- sprint list responses expose canonical status, fidelity, runtime summary, and allowed actions
- legacy `SPRINT_COMPLETE` shell state renders as planning-complete rather than terminal-project-complete

### Frontend Tests

- the sidebar remains a planning tracker rather than a repeated sprint timeline
- the overview distinguishes planning status from sprint runtime
- landing priority is `active -> planned -> hub/history`
- completed sprint views are read-only
- the shell no longer presents the whole project as permanently finished after the first sprint cycle

## Scope Boundary

This design is intentionally limited to:

- sprint lifecycle/runtime semantics
- project-shell versus sprint-workspace UX contract
- backend invariants
- API shape
- migration and testing boundaries

It does not include:

- multi-sprint queue management
- automatic rollover behavior
- recurring global stepper redesign
- detailed implementation sequencing

## Repository Touchpoints

The current redesign is anchored in the existing sprint and shell implementation across:

- [`agile_sqlmodel.py`](../../../agile_sqlmodel.py)
- [`api.py`](../../../api.py)
- [`frontend/project.js`](../../../frontend/project.js)
- [`frontend/project.html`](../../../frontend/project.html)
- [`orchestrator_agent/fsm/states.py`](../../../orchestrator_agent/fsm/states.py)
- [`tests/test_api_sprint_flow.py`](../../../tests/test_api_sprint_flow.py)

These files already contain the partial lifecycle concepts that this design formalizes into a single contract.
