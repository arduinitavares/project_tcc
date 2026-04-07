# Sprint Read Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `GET /api/projects/{project_id}/sprints` and `GET /api/projects/{project_id}/sprints/{sprint_id}` orchestration out of `api.py` and into public functions in `services/phases/sprint_service.py`.

**Architecture:** Keep route registration in `routers/sprint.py` and keep product existence checks in `api.py`. Extract the read-path branching and response assembly into service functions using dependency injection for loading and serialization, so this stays incremental and does not force a repository refactor in the same patch.

**Tech Stack:** FastAPI, pytest, pytest-asyncio, TestClient, SQLModel

---

### Task 1: Add Red Tests For Sprint Read Service Functions

**Files:**
- Modify: `tests/test_sprint_phase_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_list_saved_sprints_returns_serialized_items_and_runtime_summary():
    ...


def test_get_saved_sprint_detail_rejects_missing_sprint():
    ...


def test_get_saved_sprint_detail_returns_serialized_detail_and_summary():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: FAIL with missing `list_saved_sprints` and `get_saved_sprint_detail` service symbols.


### Task 2: Implement Public Read Service Functions

**Files:**
- Modify: `services/phases/sprint_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Add `list_saved_sprints(...)`**

Implement `list_saved_sprints(...)` to own:
- loading all saved sprints through an injected callback
- runtime summary construction through an injected callback
- serialized list payload assembly

- [ ] **Step 2: Add `get_saved_sprint_detail(...)`**

Implement `get_saved_sprint_detail(...)` to own:
- sprint not found decision
- loading all saved sprints for runtime summary
- serialized detail payload assembly

- [ ] **Step 3: Run service tests**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: PASS


### Task 3: Delegate `api.py` Sprint Read Handlers

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_sprint_flow.py`
- Test: `tests/test_api_route_registration.py`

- [ ] **Step 1: Update `list_project_sprints(...)` and `get_project_sprint(...)`**

Keep in `api.py`:
- product existence check
- session factory / DB-scoped helper callbacks

Move into service:
- list payload assembly
- sprint not-found branching
- detailed response payload shape

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
