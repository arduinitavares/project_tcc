# Story Close Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move story close read/write orchestration out of `api.py` and into `services/story_close_service.py`.

**Architecture:** Keep SQLModel session wiring in `api.py`, but extract story/sprint membership validation, readiness computation, close eligibility, and close mutation orchestration into a dedicated service module. This keeps the refactor incremental while removing another unit of delivery-layer business logic.

**Tech Stack:** FastAPI, pytest, TestClient, SQLModel

---

### Task 1: Add Red Tests For Story Close Service Functions

**Files:**
- Add: `tests/test_story_close_service.py`
- Test: `tests/test_story_close_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_get_story_close_readiness_marks_done_story_ineligible():
    ...


def test_get_story_close_readiness_reports_no_executable_tasks():
    ...


def test_close_story_rejects_incomplete_actionable_tasks():
    ...


def test_close_story_marks_story_done_and_returns_payload():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_story_close_service.py -q`
Expected: FAIL with missing `services.story_close_service`.


### Task 2: Implement Story Close Service Functions

**Files:**
- Add: `services/story_close_service.py`
- Test: `tests/test_story_close_service.py`

- [ ] **Step 1: Add `StoryCloseServiceError` and public close helpers**

Implement:
- `get_story_close_readiness(...)`
- `close_story(...)`

They should own:
- story / sprint / sprint-story validation
- readiness summary assembly
- no-executable-task and not-all-done gating
- already-done / already-accepted gating
- evidence JSON normalization
- returned response payload shaping

- [ ] **Step 2: Run service tests**

Run: `uv run pytest tests/test_story_close_service.py -q`
Expected: PASS


### Task 3: Delegate Story Close Handlers In `api.py`

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_story_close.py`

- [ ] **Step 1: Update story close handlers**

Keep in `api.py`:
- session factory
- DB-scoped loader/persist callbacks
- `StoryCompletionLog` ORM construction

Move into service:
- readiness computation
- close eligibility checks
- response assembly after story close

- [ ] **Step 2: Run regression tests**

Run:

```bash
uv run pytest \
  tests/test_story_close_service.py \
  tests/test_api_story_close.py -q
```

Then run:

```bash
uv run pytest \
  tests/test_sprint_phase_service.py \
  tests/test_packet_service.py \
  tests/test_task_execution_service.py \
  tests/test_story_close_service.py \
  tests/test_api_route_registration.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_sprint_close.py \
  tests/test_api_story_close.py \
  tests/test_api_task_execution.py -q
```

Expected: PASS
