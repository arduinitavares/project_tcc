# Architecture Review Report (Codex V2)
## AgenticFlow / `agileforge`

This revision incorporates valid feedback on the first Codex report:

- it keeps the pattern/architecture decision framing;
- it adds concrete code references and execution-oriented findings;
- it upgrades the target architecture to use a real `services/phases/` application layer rather than router-adjacent helpers.

## 1. Executive Summary

The codebase is still best treated as a modular monolith. That was the right high-level choice, and the repo already contains useful structural pieces: `services/`, `repositories/`, `orchestrator_agent/fsm/`, and `utils/`.

The main problem is not the choice of monolith versus services. The main problem is that the HTTP delivery layer never finished the architectural split, so too much orchestration accumulated in [`api.py`](/Users/aaat/projects/agileforge/api.py). A second hotspot, [`tools/spec_tools.py`](/Users/aaat/projects/agileforge/tools/spec_tools.py), has grown into a similar multi-responsibility module around specification lifecycle and validation.

### Revised Top Issues

| # | Problem | Severity |
|---|---------|----------|
| 1 | [`api.py`](/Users/aaat/projects/agileforge/api.py) is a 4,297-line god file combining routes, DTOs, workflow state mutation, packet building, and direct DB access | Critical |
| 2 | Several frontend-expected endpoints are implemented as plain functions with no FastAPI decorators | High |
| 3 | Route handlers and helper functions open raw SQLModel sessions directly, bypassing the repository boundary | High |
| 4 | Workflow transition and attempt-recording logic is duplicated across phases instead of being centralized | High |
| 5 | [`tools/spec_tools.py`](/Users/aaat/projects/agileforge/tools/spec_tools.py) is a 2,905-line second god module | High |
| 6 | [`utils/schemes.py`](/Users/aaat/projects/agileforge/utils/schemes.py) mixes agent schemas, API schemas, and ORM-coupled imports | Medium |
| 7 | [`tools/orchestrator_tools.py`](/Users/aaat/projects/agileforge/tools/orchestrator_tools.py) mixes query concerns, cache hydration, and active-project session mutation | Medium |

### Architectural Decision Tree For This Repo

1. Is a monolith acceptable?
   Yes.

2. Do multiple entrypoints need to reuse the same workflow logic?
   Yes: FastAPI routes, ADK tools, scripts, and tests.

3. Is the business/workflow logic complex enough that free-form transaction scripts in routes no longer scale?
   Yes.

4. Do we need full DDD / full Data Mapper / CQRS / event-driven architecture?
   No.

5. What is the best-fit target?
   A layered modular monolith with:
   - thin routers
   - `services/phases/*` application services
   - selective repositories
   - thin ADK/tool adapters
   - centralized workflow/session state and transitions

## 2. Concrete Findings

### Finding 1: `api.py` owns too many responsibilities

- File size: [`api.py`](/Users/aaat/projects/agileforge/api.py) is 4,297 lines.
- It defines 33 FastAPI-decorated endpoints and a large private helper surface.
- It also owns:
  - workflow session hydration: [`_ensure_session`](/Users/aaat/projects/agileforge/api.py#L500), [`_hydrate_context`](/Users/aaat/projects/agileforge/api.py#L515)
  - packet construction: [`_build_story_packet`](/Users/aaat/projects/agileforge/api.py#L1177), [`_build_task_packet`](/Users/aaat/projects/agileforge/api.py#L1298)
  - setup orchestration: [`_run_setup`](/Users/aaat/projects/agileforge/api.py#L1485)
  - story runtime lifecycle glue: [`_ensure_story_runtime`](/Users/aaat/projects/agileforge/api.py#L2433), [`_sync_story_legacy_mirrors`](/Users/aaat/projects/agileforge/api.py#L2688)
  - sprint execution/close behaviors: [`save_project_sprint`](/Users/aaat/projects/agileforge/api.py#L4108), [`start_project_sprint`](/Users/aaat/projects/agileforge/api.py#L4197)

Why this matters:

- any workflow change touches the delivery layer;
- merge conflicts will concentrate here;
- imports of `api.py` pull in the whole world;
- the file is now acting as router, application service, serializer, and workflow coordinator simultaneously.

### Finding 2: Several frontend-expected endpoints are not registered as routes

The frontend calls these endpoints:

- [`frontend/project.js:3066`](/Users/aaat/projects/agileforge/frontend/project.js#L3066) and [`frontend/project.js:3110`](/Users/aaat/projects/agileforge/frontend/project.js#L3110) call sprint close URLs
- [`frontend/project.js:3855`](/Users/aaat/projects/agileforge/frontend/project.js#L3855), [`frontend/project.js:3888`](/Users/aaat/projects/agileforge/frontend/project.js#L3888), [`frontend/project.js:3938`](/Users/aaat/projects/agileforge/frontend/project.js#L3938) call packet URLs
- [`frontend/project.js:4011`](/Users/aaat/projects/agileforge/frontend/project.js#L4011), [`frontend/project.js:4132`](/Users/aaat/projects/agileforge/frontend/project.js#L4132) call task execution URLs
- [`frontend/project.js:4173`](/Users/aaat/projects/agileforge/frontend/project.js#L4173), [`frontend/project.js:4289`](/Users/aaat/projects/agileforge/frontend/project.js#L4289) call story close URLs

But the corresponding functions in [`api.py`](/Users/aaat/projects/agileforge/api.py) are plain functions with no `@app.get` / `@app.post` decorators:

- [`get_sprint_close`](/Users/aaat/projects/agileforge/api.py#L3663)
- [`post_sprint_close`](/Users/aaat/projects/agileforge/api.py#L3694)
- [`get_project_task_packet`](/Users/aaat/projects/agileforge/api.py#L3748)
- [`get_project_story_packet`](/Users/aaat/projects/agileforge/api.py#L3778)
- [`get_task_execution`](/Users/aaat/projects/agileforge/api.py#L3811)
- [`post_task_execution`](/Users/aaat/projects/agileforge/api.py#L3882)
- [`get_story_close`](/Users/aaat/projects/agileforge/api.py#L3953)
- [`post_story_close`](/Users/aaat/projects/agileforge/api.py#L4024)

Observed usage:

- I found direct test usage of [`get_task_execution`](/Users/aaat/projects/agileforge/tests/test_api_task_execution.py#L200), but no FastAPI route registration or alternate `add_api_route` wiring.

Why this matters:

- this is either dead code, missing route wiring, or a test-only helper surface masquerading as endpoints;
- regardless, it is a real architectural smell and likely a functional bug.

### Finding 3: Raw DB access is spread through the API layer

Direct `Session(get_engine())` usage in [`api.py`](/Users/aaat/projects/agileforge/api.py) appears at:

- [`api.py:790`](/Users/aaat/projects/agileforge/api.py#L790)
- [`api.py:3366`](/Users/aaat/projects/agileforge/api.py#L3366)
- [`api.py:3639`](/Users/aaat/projects/agileforge/api.py#L3639)
- [`api.py:3667`](/Users/aaat/projects/agileforge/api.py#L3667)
- [`api.py:3698`](/Users/aaat/projects/agileforge/api.py#L3698)
- [`api.py:3756`](/Users/aaat/projects/agileforge/api.py#L3756)
- [`api.py:3789`](/Users/aaat/projects/agileforge/api.py#L3789)
- [`api.py:3815`](/Users/aaat/projects/agileforge/api.py#L3815)
- [`api.py:3889`](/Users/aaat/projects/agileforge/api.py#L3889)
- [`api.py:3957`](/Users/aaat/projects/agileforge/api.py#L3957)
- [`api.py:4028`](/Users/aaat/projects/agileforge/api.py#L4028)
- [`api.py:4205`](/Users/aaat/projects/agileforge/api.py#L4205)

The most concrete example is [`delete_project_story`](/Users/aaat/projects/agileforge/api.py#L3198), which performs a multi-table delete flow directly in the route layer.

Why this matters:

- it bypasses repository abstractions;
- route handlers are doing transaction scripting and persistence orchestration;
- test seams become much worse.

### Finding 4: Workflow transition and attempt-recording logic is duplicated

Duplicated phase triplets:

- vision: [`_ensure_vision_attempts`](/Users/aaat/projects/agileforge/api.py#L1442), [`_record_vision_attempt`](/Users/aaat/projects/agileforge/api.py#L1449), [`_set_vision_fsm_state`](/Users/aaat/projects/agileforge/api.py#L1478)
- backlog: [`_ensure_backlog_attempts`](/Users/aaat/projects/agileforge/api.py#L1987), [`_record_backlog_attempt`](/Users/aaat/projects/agileforge/api.py#L1994), [`_set_backlog_fsm_state`](/Users/aaat/projects/agileforge/api.py#L2023)
- roadmap: [`_ensure_roadmap_attempts`](/Users/aaat/projects/agileforge/api.py#L2203), [`_record_roadmap_attempt`](/Users/aaat/projects/agileforge/api.py#L2210), [`_set_roadmap_fsm_state`](/Users/aaat/projects/agileforge/api.py#L2239)
- sprint: [`_ensure_sprint_attempts`](/Users/aaat/projects/agileforge/api.py#L3358), [`_record_sprint_attempt`](/Users/aaat/projects/agileforge/api.py#L3406)

There is also duplicated route-local FSM validation such as [`valid_states`](/Users/aaat/projects/agileforge/api.py#L3478) inside sprint generation.

Why this matters:

- the FSM is not the only source of truth anymore;
- transition rule changes require edits in multiple places;
- one missing update will create phase drift.

### Finding 5: `tools/spec_tools.py` is now a second god module

File size: [`tools/spec_tools.py`](/Users/aaat/projects/agileforge/tools/spec_tools.py) is 2,905 lines.

It currently mixes:

- spec save/link/read: [`save_project_specification`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L143), [`link_spec_to_product`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L367), [`read_project_specification`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L502)
- preview/compile lifecycle: [`preview_spec_authority`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L633), [`compile_spec_authority`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L1141), [`compile_spec_authority_for_version`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L1260), [`update_spec_and_compile_authority`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L1506)
- acceptance/status: [`ensure_accepted_spec_authority`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L1654), [`check_spec_authority_status`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L1900)
- story validation: [`validate_story_with_spec_authority`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L2553)

Why this matters:

- spec lifecycle and story validation are related, but not the same responsibility;
- this file will keep attracting changes from multiple unrelated workflows.

### Finding 6: `api.py` imports private helpers from `spec_tools`

`api.py` imports:

- [`_compute_story_input_hash`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L2153)
- [`_load_compiled_artifact`](/Users/aaat/projects/agileforge/tools/spec_tools.py#L854)

via:

- [`api.py:112-116`](/Users/aaat/projects/agileforge/api.py#L112)

Why this matters:

- underscore-prefixed helpers are being treated as cross-module API;
- it shows missing ownership boundaries between spec logic and API packet/validation logic.

### Finding 7: `utils/schemes.py` has real layering leakage

File size: [`utils/schemes.py`](/Users/aaat/projects/agileforge/utils/schemes.py) is 711 lines.

It contains mid-file ORM imports:

- [`utils/schemes.py:572`](/Users/aaat/projects/agileforge/utils/schemes.py#L572): `from agile_sqlmodel import TaskStatus, TaskAcceptanceResult`
- [`utils/schemes.py:637`](/Users/aaat/projects/agileforge/utils/schemes.py#L637): `from agile_sqlmodel import StoryResolution`

Why this matters:

- a supposedly shared schema module depends on the ORM layer;
- agent schemas, API response schemas, and ORM-coupled enums are mixed in one file.

### Finding 8: `tools/orchestrator_tools.py` is too mixed to stay as-is

Key functions:

- query/read model: [`fetch_sprint_candidates`](/Users/aaat/projects/agileforge/tools/orchestrator_tools.py#L459)
- state bootstrap: [`get_real_business_state`](/Users/aaat/projects/agileforge/tools/orchestrator_tools.py#L634)
- active-project session mutation: [`select_project`](/Users/aaat/projects/agileforge/tools/orchestrator_tools.py#L654)

Why this matters:

- read models, caches, and session state mutation are different reasons to change;
- `services/workflow.py` and `services/sprint_input.py` currently depend on this mixed module.

## 3. Revised Architectural Position

The right target is still a **layered modular monolith**, but the missing layer should be explicit:

```text
FastAPI routers
    -> services/phases/*
        -> services/specs/* or agent runtime wrappers
            -> repositories/*
                -> models / db
```

### What Belongs Where

- `api/routers/*`
  - HTTP only
  - request/response mapping
  - status codes
  - dependency injection

- `services/phases/*`
  - generate/save/retry/delete orchestration per workflow phase
  - attempt recording
  - session-state updates
  - transition decisions delegated to one transition helper

- `services/story_runtime.py`
  - story-agent invocation only
  - request payload normalization
  - raw LLM output parsing/validation
  - no session mutation, no feedback absorption, no legacy mirror syncing

- `services/phases/story_service.py`
  - owns story workflow state
  - owns draft projection / request projection / feedback absorption
  - owns save payload derivation, retry behavior, and legacy-state migration boundaries
  - is the only place that should coordinate `story_runtime.py` with workflow/session state

- `services/specs/*`
  - specification lifecycle
  - compiler invocation
  - story validation

- `repositories/*`
  - all non-trivial DB access
  - multi-table transaction operations
  - query helpers for packets, sprint execution, and close flows

- `orchestrator_agent/agent_tools/*`
  - thin ADK adapters over phase/spec services
  - no unique business rules

- `api/_internal/*` or `api/internal/*`
  - temporary extraction landing zone only during the router split
  - acceptable for helper relocation in the first cut
  - must not become the long-term home for orchestration logic

## 4. Revised File Moves

### Extract from `api.py`

Transitional note:

- during the first router split, helpers may remain in [`api.py`](/Users/aaat/projects/agileforge/api.py) or move to a temporary `api/_internal/` module;
- that is a staging step only;
- by the end of Phase 3, orchestration helpers should live in `services/phases/*`, packet-building helpers in `services/packets/*`, and persistence/query logic in `repositories/*`.

- to `api/routers/projects.py`
  - project CRUD/state routes

- to `api/routers/vision.py`
  - `generate_project_vision`
  - `get_project_vision_history`
  - `save_project_vision`

- to `api/routers/backlog.py`
  - backlog generate/history/save routes

- to `api/routers/roadmap.py`
  - roadmap generate/history/save routes

- to `api/routers/story.py`
  - story pending/generate/retry/history/save/merge/delete/complete routes

- to `api/routers/sprint.py`
  - sprint generate/history/reset/list/get/save/start routes
  - sprint close/task execution/story close/packet endpoints once properly registered

- to `services/phases/story_service.py`
  - story runtime orchestration currently split between `api.py` and `services/story_runtime.py`
  - specifically: logic around [`_ensure_story_runtime`](/Users/aaat/projects/agileforge/api.py#L2433), retryability, save payload derivation, resolution summary, and legacy mirror syncing

- to `services/phases/workflow_state.py`
  - generic attempt recording
  - generic per-phase assessment projection helpers
  - concrete first abstraction:

```python
def ensure_phase_attempts(
    state: dict[str, Any],
    *,
    phase_key: str,
) -> list[dict[str, Any]]: ...


def record_phase_attempt(
    state: dict[str, Any],
    *,
    phase_key: str,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any],
    is_complete: bool,
    failure_meta: dict[str, Any] | None = None,
) -> int: ...


def set_phase_fsm_state(
    state: dict[str, Any],
    *,
    is_complete: bool,
    review_state: str,
    interview_state: str,
    override_state: str | None = None,
) -> str: ...
```

  - `phase_key` would replace the current hard-coded variants such as `vision_attempts`, `backlog_attempts`, `roadmap_attempts`, and `sprint_attempts`
  - `override_state` is an escape hatch for asymmetric phases such as sprint planning, where the target-state mapping is not a simple review/interview pair

- to `services/packets/packet_service.py`
  - [`_build_story_packet`](/Users/aaat/projects/agileforge/api.py#L1177)
  - [`_build_task_packet`](/Users/aaat/projects/agileforge/api.py#L1298)
  - supporting packet context loaders

### Split `tools/spec_tools.py`

- `services/specs/lifecycle_service.py`
  - spec save/read/link/version/approval

- `services/specs/compiler_service.py`
  - preview/compile/update-compile

- `services/specs/story_validation_service.py`
  - validate story against accepted authority

### Split `agile_sqlmodel.py`

- `models/enums.py`
  - status enums and workflow enums

- `models/core.py`
  - `Product`, `Team`, `TeamMember`, `Theme`, `Epic`, `Feature`, `Sprint`, `UserStory`, `Task`

- `models/specs.py`
  - `SpecRegistry`, `CompiledSpecAuthority`, `SpecAuthorityAcceptance`

- `models/events.py`
  - `WorkflowEvent`, `TaskExecutionLog`, `StoryCompletionLog`

- `models/db.py`
  - `get_engine`, DB bootstrap, migration bootstrap

- keep [`agile_sqlmodel.py`](/Users/aaat/projects/agileforge/agile_sqlmodel.py) as a compatibility shim during migration
  - re-export symbols from `models/*`
  - migrate imports incrementally rather than in one big bang

## 5. Revised Migration Plan

### Phase 1: Safety + Clarification

- Register or explicitly retire the 8 currently undecorated close/execution/packet functions.
- Add a fast regression test confirming those frontend URLs are registered.
- Extract only route declarations from `api.py` into `api/routers/*`, keeping existing helper calls.
- During this phase, helper functions may stay in [`api.py`](/Users/aaat/projects/agileforge/api.py) or move to a temporary `api/_internal/` module.
- Do not move orchestration logic into `api/_internal/` permanently; it is a transition seam, not the target architecture.

Validation:

- startup succeeds
- route table includes close/execution/packet endpoints
- verify with:
  - [tests/test_api_sprint_close.py](/Users/aaat/projects/agileforge/tests/test_api_sprint_close.py)
  - [tests/test_api_task_execution.py](/Users/aaat/projects/agileforge/tests/test_api_task_execution.py)
  - [tests/test_api_sprint_flow.py](/Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py)

### Phase 2: Introduce `services/phases/*`

- Create:
  - `services/phases/vision_service.py`
  - `services/phases/backlog_service.py`
  - `services/phases/roadmap_service.py`
  - `services/phases/story_service.py`
  - `services/phases/sprint_service.py`
- Move route orchestration into these services.
- Routers become thin wrappers over service calls.
- If any helper had to move out of `api.py` early, it may temporarily sit in `api/_internal/` during this phase.
- Hard rule: by the end of Phase 3, no phase orchestration helper should remain in `api.py` or `api/_internal/`.

Validation:

- routers no longer open sessions or call save tools directly
- service unit tests cover generate/save/retry behavior
- verify with:
  - [tests/test_api_vision_flow.py](/Users/aaat/projects/agileforge/tests/test_api_vision_flow.py)
  - [tests/test_api_story_interview_flow.py](/Users/aaat/projects/agileforge/tests/test_api_story_interview_flow.py)
  - [tests/test_api_sprint_flow.py](/Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py)
  - [tests/test_packet_renderer.py](/Users/aaat/projects/agileforge/tests/test_packet_renderer.py)
- Coverage gap:
  - there is no dedicated API packet endpoint test file today;
  - when `_build_story_packet` and `_build_task_packet` move to `services/packets/packet_service.py`, add or extend API-level packet endpoint tests so the route wiring is explicitly covered

### Phase 3: Centralize workflow state and transitions

- Extract the duplicated attempt-recording pattern.
- Create a single workflow-state helper and transition facade.
- Stop redefining phase transitions in route-local checks unless they are intentionally stricter and documented.
- Start with this unified abstraction in `services/phases/workflow_state.py`:

```python
def ensure_phase_attempts(state: dict[str, Any], *, phase_key: str) -> list[dict[str, Any]]: ...

def record_phase_attempt(
    state: dict[str, Any],
    *,
    phase_key: str,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any],
    is_complete: bool,
    failure_meta: dict[str, Any] | None = None,
) -> int: ...

def set_phase_fsm_state(
    state: dict[str, Any],
    *,
    is_complete: bool,
    review_state: str,
    interview_state: str,
    override_state: str | None = None,
) -> str: ...
```

- Note: `set_phase_fsm_state()` works naturally for vision/backlog/roadmap, but sprint planning is asymmetric.
- Sprint currently maps to `SPRINT_DRAFT` when complete and `SPRINT_SETUP` when incomplete, while also interacting with `STORY_PERSISTENCE` and `SPRINT_PERSISTENCE`.
- Implementation should therefore allow an explicit override path or a sprint-specific wrapper rather than forcing sprint through the exact same two-state shape.

Validation:

- changing attempt metadata requires edits in one place
- FSM transition rules are testable without importing `api.py`
- verify with:
  - [tests/test_fsm_story_transitions.py](/Users/aaat/projects/agileforge/tests/test_fsm_story_transitions.py)
  - [tests/test_workflow_session_bootstrap.py](/Users/aaat/projects/agileforge/tests/test_workflow_session_bootstrap.py)
  - [tests/test_sprint_planner_tool_registration.py](/Users/aaat/projects/agileforge/tests/test_sprint_planner_tool_registration.py)

### Phase 4: Split spec lifecycle

- Break up `tools/spec_tools.py`.
- Replace private-helper imports from `api.py` with public service interfaces.

Validation:

- `api.py` no longer imports underscore-prefixed functions
- story validation and spec compilation tests run against separate services
- verify with:
  - [tests/test_spec_authority.py](/Users/aaat/projects/agileforge/tests/test_spec_authority.py)
  - [tests/test_spec_authority_compile_tool.py](/Users/aaat/projects/agileforge/tests/test_spec_authority_compile_tool.py)
  - [tests/test_update_spec_and_compile_authority.py](/Users/aaat/projects/agileforge/tests/test_update_spec_and_compile_authority.py)
  - [tests/test_story_validation_pinning.py](/Users/aaat/projects/agileforge/tests/test_story_validation_pinning.py)

### Phase 5: Clean secondary hotspots

- Split `utils/schemes.py` into agent schemas and API schemas.
- Split mixed concerns in `tools/orchestrator_tools.py`.

Validation:

- utility/schema modules stop importing ORM enums mid-file
- service layer dependencies become easier to trace
- verify with:
  - [tests/test_orchestrator_tools.py](/Users/aaat/projects/agileforge/tests/test_orchestrator_tools.py)
  - [tests/test_orchestrator_tools_unittest.py](/Users/aaat/projects/agileforge/tests/test_orchestrator_tools_unittest.py)
  - [tests/test_select_project_hydration.py](/Users/aaat/projects/agileforge/tests/test_select_project_hydration.py)
  - [tests/test_story_runtime.py](/Users/aaat/projects/agileforge/tests/test_story_runtime.py)

### Phase 6: Package Models Behind a Stable Import Shim

- Introduce a `models/` package and move ORM types out of [`agile_sqlmodel.py`](/Users/aaat/projects/agileforge/agile_sqlmodel.py).
- Keep [`agile_sqlmodel.py`](/Users/aaat/projects/agileforge/agile_sqlmodel.py) as a compatibility shim that re-exports the new package during the migration window.
- Migrate imports incrementally across API, services, repositories, tools, and tests.

Validation:

- import sites continue to work through the shim
- model packaging is transparent to runtime behavior
- verify with:
  - [tests/test_db_migrations_sprint_lifecycle.py](/Users/aaat/projects/agileforge/tests/test_db_migrations_sprint_lifecycle.py)
  - [tests/test_api_sprint_close.py](/Users/aaat/projects/agileforge/tests/test_api_sprint_close.py)
  - [tests/test_api_story_interview_flow.py](/Users/aaat/projects/agileforge/tests/test_api_story_interview_flow.py)
  - [tests/test_api_sprint_flow.py](/Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py)
  - [tests/test_api_task_execution.py](/Users/aaat/projects/agileforge/tests/test_api_task_execution.py)

## 6. Final Recommendation

The critique was right on the main point: my first report was too strategic and not concrete enough for execution. The strongest upgrades are:

- keep the decision-tree framing;
- explicitly adopt `services/phases/*` as the application layer;
- treat the undecorated endpoint-like functions as an immediate architecture/behavioral issue;
- elevate `tools/spec_tools.py` into the main hotspot list.

The right refactor is still incremental. No rewrite is needed. The smallest high-leverage change set is:

1. split `api.py` into routers;
2. create `services/phases/*`;
3. centralize workflow state/attempt logic;
4. split `tools/spec_tools.py`.
