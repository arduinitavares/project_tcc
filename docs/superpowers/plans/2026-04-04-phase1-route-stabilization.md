# Phase 1 Route Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register the currently undecorated sprint close, story close, task execution, and packet handlers as real FastAPI endpoints without changing their business behavior.

**Architecture:** Keep the current monolith intact for this first slice. Add a narrow regression test around route registration, then wire the existing handler functions onto the FastAPI app with minimal code movement so the existing API tests become meaningful again.

**Tech Stack:** FastAPI, SQLModel, pytest, TestClient

---

### Task 1: Add Endpoint Registration Regression Coverage

**Files:**
- Create: `tests/test_api_route_registration.py`
- Modify: none
- Test: `tests/test_api_route_registration.py`

- [ ] **Step 1: Write the failing test**

```python
import api as api_module


def test_manual_sprint_execution_and_packet_routes_are_registered():
    routes = {
        (route.path, tuple(sorted(route.methods or ())))
        for route in api_module.app.routes
        if hasattr(route, "path")
    }

    expected = {
        ("/api/projects/{project_id}/sprints/{sprint_id}/close", ("GET",)),
        ("/api/projects/{project_id}/sprints/{sprint_id}/close", ("POST",)),
        (
            "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet",
            ("GET",),
        ),
        (
            "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/packet",
            ("GET",),
        ),
        (
            "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
            ("GET",),
        ),
        (
            "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
            ("POST",),
        ),
        (
            "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
            ("GET",),
        ),
        (
            "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
            ("POST",),
        ),
    }

    missing = expected - routes
    assert not missing, f"Missing route registrations: {sorted(missing)}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_route_registration.py -q`
Expected: FAIL with missing route registrations for the close, execution, and packet paths.

- [ ] **Step 3: Keep the existing flow tests as the behavior safety net**

Use these existing HTTP tests as the behavior contract once the routes exist:

```bash
pytest \
  tests/test_api_sprint_close.py \
  tests/test_api_story_close.py \
  tests/test_api_task_execution.py \
  tests/test_api_sprint_flow.py -k "packet" -q
```

Expected: these currently fail or partially fail before registration is fixed, then become the green bar after the route wiring lands.


### Task 2: Register the Existing Handlers on `app`

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_route_registration.py`

- [ ] **Step 1: Add FastAPI decorators to the existing handlers**

Apply these route definitions directly on the current functions:

```python
@app.get("/api/projects/{project_id}/sprints/{sprint_id}/close")
def get_sprint_close(...): ...


@app.post("/api/projects/{project_id}/sprints/{sprint_id}/close")
def post_sprint_close(...): ...


@app.get("/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet")
async def get_project_task_packet(...): ...


@app.get("/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/packet")
async def get_project_story_packet(...): ...


@app.get("/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution")
def get_task_execution(...): ...


@app.post("/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution")
def post_task_execution(...): ...


@app.get("/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close")
def get_story_close(...): ...


@app.post("/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close")
def post_story_close(...): ...
```

- [ ] **Step 2: Run the registration test**

Run: `pytest tests/test_api_route_registration.py -q`
Expected: PASS

- [ ] **Step 3: Run the existing flow tests**

Run:

```bash
pytest \
  tests/test_api_sprint_close.py \
  tests/test_api_story_close.py \
  tests/test_api_task_execution.py \
  tests/test_api_sprint_flow.py -k "packet" -q
```

Expected: PASS


### Task 3: Keep the Fix Tight and Prepare the Next Phase

**Files:**
- Modify: `docs/ARCHITECTURE_REVIEW_CODEX_V2.md` (only if implementation discovers a mismatch)
- Test: the same targeted pytest commands from Tasks 1-2

- [ ] **Step 1: Verify there was no accidental architectural expansion**

Confirm these constraints still hold:

```text
- No new business logic extracted yet
- No new persistence helpers added in api.py
- No router split attempted in the same patch
- Only route registration and regression coverage changed
```

- [ ] **Step 2: Record the next extraction target**

After the tests pass, the next safe move is:

```text
Extract the newly registered sprint/story/task packet and close endpoints into api/routers/sprint.py,
keeping helper calls unchanged in the first cut.
```

- [ ] **Step 3: Commit**

```bash
git add api.py tests/test_api_route_registration.py docs/superpowers/plans/2026-04-04-phase1-route-stabilization.md
git commit -m "test: stabilize manual sprint and execution route registration"
```
