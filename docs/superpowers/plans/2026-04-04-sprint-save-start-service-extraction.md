# Sprint Save And Start Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `sprint/save` and `sprints/{sprint_id}/start` handler orchestration out of `api.py` and into public functions in `services/phases/sprint_service.py`.

**Architecture:** Keep route registration in `routers/sprint.py` and keep product existence checks in `api.py`. Extract the save/start decision logic into service functions, using dependency injection for session/hydration/tool operations so this stays incremental and does not force a repository refactor in the same patch.

**Tech Stack:** FastAPI, pytest, pytest-asyncio, TestClient, SQLModel

---

### Task 1: Add Red Tests For Save And Start Service Functions

**Files:**
- Modify: `tests/test_sprint_phase_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
@pytest.mark.asyncio
async def test_save_sprint_plan_sanitizes_assessment_and_updates_state():
    ...


@pytest.mark.asyncio
async def test_save_sprint_plan_maps_open_sprint_conflict_to_phase_error():
    ...


def test_start_saved_sprint_rejects_other_active_sprint():
    ...


def test_start_saved_sprint_returns_existing_active_detail_without_persisting():
    ...


def test_start_saved_sprint_persists_planned_sprint_and_returns_detail():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: FAIL with missing `save_sprint_plan` and `start_saved_sprint` service symbols.


### Task 2: Implement Public Save/Start Service Functions

**Files:**
- Modify: `services/phases/sprint_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Add `save_sprint_plan(...)`**

Implement `save_sprint_plan(...)` to own:
- stale working-set reset
- session assessment validation
- `SprintPlannerOutput` validation
- hydrated context mutation
- `save_sprint_plan_tool(...)` invocation
- state transition to `SPRINT_PERSISTENCE`

- [ ] **Step 2: Add `start_saved_sprint(...)`**

Implement `start_saved_sprint(...)` to own:
- “not found / other active / completed sprint” decisions
- “already started” fast path
- “start planned sprint” transition path
- return payload assembly through injected summary/serialization callbacks

- [ ] **Step 3: Run service tests**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: PASS


### Task 3: Delegate `api.py` Save/Start Handlers

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_sprint_flow.py`
- Test: `tests/test_api_route_registration.py`

- [ ] **Step 1: Update `save_project_sprint(...)` and `start_project_sprint(...)`**

Keep in `api.py`:
- product existence check
- `_load_current_planned_sprint_id(project_id)`
- session factory / DB-scoped helper callbacks

Move into service:
- save flow orchestration
- start flow branching and returned sprint detail payload shape

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
  docs/superpowers/plans/2026-04-04-sprint-save-start-service-extraction.md
git commit -m "refactor: move sprint save and start orchestration into service"
```
