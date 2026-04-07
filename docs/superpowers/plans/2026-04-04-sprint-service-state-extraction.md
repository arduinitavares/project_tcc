# Sprint Phase State Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move sprint planner state and attempt-tracking logic out of `api.py` into a pure `services/phases/sprint_service.py` module without changing API behavior.

**Architecture:** Keep HTTP routes and DB lookups where they are for now, but extract sprint-specific state mutation and normalization into a dedicated service module. This creates the first real `services/phases/*` boundary while preserving the current API contracts and test surface.

**Tech Stack:** FastAPI, SQLModel, pytest, TestClient

---

### Task 1: Add Unit Tests For Sprint Phase State Logic

**Files:**
- Create: `tests/test_sprint_phase_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Write the failing tests**

```python
from services.phases.sprint_service import (
    ensure_sprint_attempts,
    normalize_sprint_output_artifact,
    record_sprint_attempt,
    reset_sprint_planner_working_set,
    reset_stale_saved_sprint_planner_working_set,
)


def test_record_sprint_attempt_updates_working_state():
    state = {}

    count = record_sprint_attempt(
        state,
        trigger="manual_refine",
        input_context={"stories": [1]},
        output_artifact={"validation_errors": [" Unsupported task_kind 'other'. "]},
        is_complete=False,
        failure_meta={"failure_stage": "planner"},
        created_at="2026-04-04T00:00:00Z",
    )

    assert count == 1
    assert state["sprint_last_input_context"] == {"stories": [1]}
    assert state["sprint_plan_assessment"]["validation_errors"] == [
        "Unsupported task_kind 'other'."
    ]
    assert state["sprint_attempts"][0]["failure_stage"] == "planner"


def test_reset_stale_saved_sprint_planner_working_set_clears_orphaned_owner():
    state = {
        "sprint_attempts": [{"created_at": "old"}],
        "sprint_last_input_context": {"stories": [1]},
        "sprint_plan_assessment": {"draft": True},
        "sprint_saved_at": "2026-04-01T00:00:00Z",
        "sprint_planner_owner_sprint_id": 9,
    }

    changed = reset_stale_saved_sprint_planner_working_set(
        state,
        current_planned_sprint_id=11,
    )

    assert changed is True
    assert state["sprint_attempts"] == []
    assert state["sprint_plan_assessment"] is None


def test_reset_stale_saved_sprint_planner_working_set_keeps_current_owner():
    state = {"sprint_planner_owner_sprint_id": 11}

    changed = reset_stale_saved_sprint_planner_working_set(
        state,
        current_planned_sprint_id=11,
    )

    assert changed is False


def test_ensure_sprint_attempts_returns_existing_list():
    attempts = [{"created_at": "2026-04-04T00:00:00Z"}]
    state = {"sprint_attempts": attempts}

    assert ensure_sprint_attempts(state) is attempts


def test_reset_sprint_planner_working_set_clears_transient_fields():
    state = {
        "sprint_attempts": [{"created_at": "old"}],
        "sprint_last_input_context": {"stories": [1]},
        "sprint_plan_assessment": {"draft": True},
        "sprint_saved_at": "2026-04-01T00:00:00Z",
        "sprint_planner_owner_sprint_id": 9,
    }

    reset_sprint_planner_working_set(state)

    assert state == {
        "sprint_attempts": [],
        "sprint_last_input_context": None,
        "sprint_plan_assessment": None,
        "sprint_saved_at": None,
        "sprint_planner_owner_sprint_id": None,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing symbol errors for `services.phases.sprint_service`.


### Task 2: Implement The Pure Sprint Phase Service

**Files:**
- Create: `services/phases/__init__.py`
- Create: `services/phases/sprint_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Write the minimal implementation**

Create `services/phases/sprint_service.py` with public helpers for:

```python
def ensure_sprint_attempts(state: dict[str, Any]) -> list[dict[str, Any]]: ...
def reset_sprint_planner_working_set(state: dict[str, Any]) -> None: ...
def reset_stale_saved_sprint_planner_working_set(
    state: dict[str, Any], *, current_planned_sprint_id: int | None
) -> bool: ...
def normalize_sprint_output_artifact(
    output_artifact: dict[str, Any] | None,
) -> dict[str, Any]: ...
def normalize_sprint_attempt(attempt: dict[str, Any]) -> dict[str, Any]: ...
def record_sprint_attempt(
    state: dict[str, Any],
    *,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any] | None,
    is_complete: bool,
    failure_meta: dict[str, Any],
    created_at: str,
) -> int: ...
```

- [ ] **Step 2: Run the service unit tests**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: PASS


### Task 3: Delegate Sprint State Logic From `api.py`

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_sprint_flow.py`
- Test: `tests/test_api_sprint_close.py`
- Test: `tests/test_api_route_registration.py`

- [ ] **Step 1: Replace local sprint state helpers with imports from the service**

Update `api.py` to import the public helpers from `services/phases/sprint_service.py`, then:

```python
planned_sprint_id = _load_current_planned_sprint_id(project_id)
reset_stale_saved_sprint_planner_working_set(
    state,
    current_planned_sprint_id=planned_sprint_id,
)
```

and:

```python
attempt_count = record_sprint_attempt(
    state,
    trigger=...,
    input_context=...,
    output_artifact=sprint_result.get("output_artifact"),
    is_complete=is_complete,
    failure_meta=_failure_meta(sprint_result),
    created_at=_now_iso(),
)
```

- [ ] **Step 2: Run the regression tests**

Run:

```bash
uv run pytest \
  tests/test_sprint_phase_service.py \
  tests/test_api_route_registration.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_sprint_close.py \
  tests/test_api_story_close.py \
  tests/test_api_task_execution.py -q
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add \
  api.py \
  services/phases/__init__.py \
  services/phases/sprint_service.py \
  tests/test_sprint_phase_service.py \
  docs/superpowers/plans/2026-04-04-sprint-service-state-extraction.md
git commit -m "refactor: extract sprint phase state service"
```
