# Task Execution Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move task execution read/write orchestration out of `api.py` and into `services/task_execution_service.py`.

**Architecture:** Keep the lower-level SQLModel session wiring in `api.py`, but extract subject validation, execution log normalization, and response payload assembly into a dedicated service module. This keeps the change incremental while removing one more pocket of workflow logic from the delivery layer.

**Tech Stack:** FastAPI, pytest, TestClient, SQLModel

---

### Task 1: Add Red Tests For Task Execution Service Functions

**Files:**
- Add: `tests/test_task_execution_service.py`
- Test: `tests/test_task_execution_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
def test_get_task_execution_history_skips_logs_without_primary_key():
    ...


def test_get_task_execution_history_rejects_cross_project_sprint():
    ...


def test_record_task_execution_rejects_non_executable_tasks():
    ...


def test_record_task_execution_normalizes_artifact_refs_and_returns_history():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_execution_service.py -q`
Expected: FAIL with missing `services.task_execution_service`.


### Task 2: Implement Task Execution Service Functions

**Files:**
- Add: `services/task_execution_service.py`
- Test: `tests/test_task_execution_service.py`

- [ ] **Step 1: Add `TaskExecutionServiceError` and public service functions**

Implement:
- `get_task_execution_history(...)`
- `record_task_execution(...)`

They should own:
- task / sprint / sprint-story validation
- history entry assembly and malformed-log skipping
- executable-task validation
- artifact-ref normalization
- read-after-write response assembly

- [ ] **Step 2: Run service tests**

Run: `uv run pytest tests/test_task_execution_service.py -q`
Expected: PASS


### Task 3: Delegate Task Execution Handlers In `api.py`

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_task_execution.py`

- [ ] **Step 1: Update task execution handlers**

Keep in `api.py`:
- session factory
- DB-scoped loader/persist callbacks
- `TaskExecutionLog` ORM construction

Move into service:
- validation and response assembly
- artifact-ref normalization
- log-to-response translation

- [ ] **Step 2: Run regression tests**

Run:

```bash
uv run pytest \
  tests/test_task_execution_service.py \
  tests/test_api_task_execution.py -q
```

Then run:

```bash
uv run pytest \
  tests/test_sprint_phase_service.py \
  tests/test_packet_service.py \
  tests/test_task_execution_service.py \
  tests/test_api_route_registration.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_sprint_close.py \
  tests/test_api_story_close.py \
  tests/test_api_task_execution.py -q
```

Expected: PASS
