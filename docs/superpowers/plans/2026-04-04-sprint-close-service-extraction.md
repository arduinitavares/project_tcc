# Sprint Close Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move sprint close read/write orchestration out of `api.py` and into public functions in `services/phases/sprint_service.py`.

**Architecture:** Keep route registration in `routers/sprint.py` and keep the lower-level DB/session callbacks in `api.py`. Extract the close eligibility, snapshot assembly, and response payload shaping into service functions using dependency injection so this stays incremental and does not force a repository refactor in the same patch.

**Tech Stack:** FastAPI, pytest, pytest-asyncio, TestClient, SQLModel

---

### Task 1: Add Red Tests For Sprint Close Service Functions

**Files:**
- Modify: `tests/test_sprint_phase_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_get_sprint_close_readiness_returns_guidance_for_completed_sprint():
    ...


def test_close_sprint_rejects_non_active_sprint():
    ...


def test_close_sprint_returns_completed_snapshot_payload():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: FAIL with missing close service symbols.


### Task 2: Implement Public Close Service Functions

**Files:**
- Modify: `services/phases/sprint_service.py`
- Test: `tests/test_sprint_phase_service.py`

- [ ] **Step 1: Add `get_sprint_close_readiness(...)`**

Implement `get_sprint_close_readiness(...)` to own:
- sprint not found decision
- eligibility / ineligible reason branching
- close-read response payload assembly

- [ ] **Step 2: Add `close_sprint(...)`**

Implement `close_sprint(...)` to own:
- sprint not found / not-active decision
- readiness computation
- close snapshot assembly
- completed response payload assembly

- [ ] **Step 3: Run service tests**

Run: `uv run pytest tests/test_sprint_phase_service.py -q`
Expected: PASS


### Task 3: Delegate `api.py` Sprint Close Handlers

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_sprint_close.py`
- Test: `tests/test_api_route_registration.py`

- [ ] **Step 1: Update `get_sprint_close(...)` and `post_sprint_close(...)`**

Keep in `api.py`:
- session factory / DB-scoped callbacks
- persistence closure for marking a sprint completed and recording the event

Move into service:
- close eligibility logic
- snapshot payload assembly
- returned response payload shape

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
