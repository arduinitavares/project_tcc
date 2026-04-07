# Story Delete Repository Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the story delete persistence flow out of `api.py` into a repository and route the state-reset orchestration through `services/phases/story_service.py`.

**Architecture:** Introduce a `StoryRepository` that owns the multi-table delete for stories, sprint mappings, story completion logs, tasks, and task execution logs. Keep the story session-state reset in the story phase service. The route should become a thin adapter over repository + service callbacks.

**Tech Stack:** FastAPI, pytest, SQLModel

---

### Task 1: Add Red Tests For Story Delete Service Function

**Files:**
- Modify: `tests/test_story_phase_service.py`
- Test: `tests/test_story_phase_service.py`

- [ ] **Step 1: Write the failing test**

Add a test for:

```python
async def test_delete_story_requirement_resets_runtime_and_clears_saved_projection():
    ...
```

The test should verify:
- the delete callback result is surfaced as `deleted_count`
- the runtime working set is reset with a reset marker
- `story_saved` and `story_outputs` are cleared for the requirement
- legacy mirrors are synchronized back into `story_attempts`

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_story_phase_service.py -q`
Expected: FAIL with missing `delete_story_requirement`.


### Task 2: Implement Story Delete Repository And Service

**Files:**
- Add: `repositories/story.py`
- Modify: `services/phases/story_service.py`
- Test: `tests/test_story_phase_service.py`

- [ ] **Step 1: Add repository delete helper**

Implement a `StoryRepository` with a method that:
- finds stories for a product + normalized requirement
- deletes sprint mappings, story completion logs, task execution logs, tasks, and stories in chunks
- commits the transaction
- returns the deleted story count

- [ ] **Step 2: Add service delete helper**

Implement:
- `delete_story_requirement(...)`

It should own:
- requirement runtime lookup
- reset marker insertion via `reset_subject_working_set`
- session-state cleanup for `story_saved` / `story_outputs`
- legacy mirror synchronization
- payload shaping for the API

- [ ] **Step 3: Run service tests**

Run: `uv run pytest tests/test_story_phase_service.py -q`
Expected: PASS


### Task 3: Delegate `delete_project_story` In `api.py`

**Files:**
- Modify: `api.py`
- Modify: `tests/test_api_delete_story.py`

- [ ] **Step 1: Update the API handler**

Keep in `api.py`:
- product lookup
- repository/session construction
- dependency wiring

Move out of `api.py`:
- multi-table delete flow
- story runtime reset orchestration
- response assembly

- [ ] **Step 2: Run regression tests**

Run:

```bash
uv run pytest \
  tests/test_story_phase_service.py \
  tests/test_api_delete_story.py -q
```

Then run:

```bash
uv run pytest \
  tests/test_sprint_phase_service.py \
  tests/test_packet_service.py \
  tests/test_task_execution_service.py \
  tests/test_story_close_service.py \
  tests/test_story_phase_service.py \
  tests/test_api_route_registration.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_sprint_close.py \
  tests/test_api_story_close.py \
  tests/test_api_story_interview_flow.py \
  tests/test_api_task_execution.py \
  tests/test_api_delete_story.py -q
```

Expected: PASS
