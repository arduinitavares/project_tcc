# Sprint Handler Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the sprint `generate`, `history`, and `planner/reset` handler orchestration out of `api.py` and into public functions in `services/phases/sprint_service.py`.

**Architecture:** Keep the sprint routes registered in `routers/sprint.py`, and keep product existence checks in `api.py` for now. Extract only the stateful orchestration logic for sprint generation and history/reset flows into public service functions so `api.py` stops owning those workflows directly.

**Tech Stack:** FastAPI, pytest, pytest-asyncio, TestClient

---

### Task 1: Add Service-Level Red Tests For Sprint Handler Orchestration

**Files:**
- Modify: `tests/test_sprint_phase_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Write the failing tests**

Add async tests for:

```python
@pytest.mark.asyncio
async def test_generate_sprint_plan_updates_state_and_returns_payload():
    ...


@pytest.mark.asyncio
async def test_generate_sprint_plan_rejects_invalid_fsm_state():
    ...


@pytest.mark.asyncio
async def test_get_sprint_history_normalizes_and_persists_legacy_attempts():
    ...


@pytest.mark.asyncio
async def test_reset_sprint_planner_rejects_existing_planned_sprint():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: FAIL with missing symbols from `services.phases.sprint_service`.


### Task 2: Implement Public Sprint Service Functions

**Files:**
- Modify: `services/phases/sprint_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Add public orchestration functions**

Implement public functions:

```python
class SprintPhaseError(Exception):
    ...


async def generate_sprint_plan(... ) -> dict[str, Any]:
    ...


async def get_sprint_history(... ) -> dict[str, Any]:
    ...


async def reset_sprint_planner(... ) -> dict[str, Any]:
    ...
```

Keep them dependency-injected for state load/save and runner invocation instead of importing `api.py`.

- [ ] **Step 2: Run the service tests**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: PASS


### Task 3: Delegate Sprint Handlers From `api.py`

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_sprint_flow.py`
- Test: `tests/test_api_route_registration.py`

- [ ] **Step 1: Update `api.py` to call the new service functions**

`api.py` should keep:
- project existence checks
- `_load_current_planned_sprint_id(project_id)`
- `_ensure_session` / `_save_session_state`

But the route handlers should delegate their orchestration to:
- `generate_sprint_plan(...)`
- `get_sprint_history(...)`
- `reset_sprint_planner(...)`

- [ ] **Step 2: Run regression tests**

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
  services/phases/sprint_service.py \
  tests/test_sprint_phase_service.py \
  docs/superpowers/plans/2026-04-04-sprint-handler-service-extraction.md
git commit -m "refactor: delegate sprint handler orchestration to service"
```
