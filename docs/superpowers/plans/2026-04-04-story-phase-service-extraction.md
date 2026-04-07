# Story Phase Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move story history/save/merge/complete-phase orchestration out of `api.py` and into `services/phases/story_service.py`.

**Architecture:** Extract story projection helpers and the shared read/write orchestration into a phase service while keeping FastAPI wiring and external dependency callbacks in `api.py`. Leave story deletion for a later repository-oriented pass because it still owns heavier multi-table persistence behavior.

**Tech Stack:** FastAPI, pytest, TestClient, SQLModel

---

### Task 1: Add Red Tests For Story Phase Service Functions

**Files:**
- Add: `tests/test_story_phase_service.py`
- Test: `tests/test_story_phase_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:

```python
async def test_get_story_history_returns_attempts_and_projection_summary():
    ...


async def test_save_story_draft_marks_requirement_saved_and_persists_state():
    ...


async def test_merge_story_resolution_persists_merged_projection():
    ...


async def test_complete_story_phase_moves_to_sprint_setup_once_story_is_saved():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_story_phase_service.py -q`
Expected: FAIL with missing `services.phases.story_service`.


### Task 2: Implement Story Phase Service Functions

**Files:**
- Add: `services/phases/story_service.py`
- Test: `tests/test_story_phase_service.py`

- [ ] **Step 1: Add `StoryPhaseError`, shared helpers, and public story-phase functions**

Implement:
- `get_story_history(...)`
- `save_story_draft(...)`
- `merge_story_resolution(...)`
- `complete_story_phase(...)`

Also move the shared story projection helpers here so the service owns:
- reusable-draft save eligibility
- merge recommendation detection
- resolution summary assembly
- roadmap requirement collection
- legacy mirror synchronization

- [ ] **Step 2: Run service tests**

Run: `uv run pytest tests/test_story_phase_service.py -q`
Expected: PASS


### Task 3: Delegate Story Handlers In `api.py`

**Files:**
- Modify: `api.py`
- Test: `tests/test_api_story_interview_flow.py`
- Test: `tests/test_api_sprint_flow.py`

- [ ] **Step 1: Update story handlers**

Delegate these handlers through `services/phases/story_service.py`:
- `get_project_story_history`
- `save_project_story`
- `merge_project_story`
- `complete_story_phase`

Use the shared service helper exports in `pending`, `generate`, `retry`, and `delete` so `api.py` stops owning the story projection rules directly.

- [ ] **Step 2: Run regression tests**

Run:

```bash
uv run pytest \
  tests/test_story_phase_service.py \
  tests/test_api_story_interview_flow.py \
  tests/test_api_sprint_flow.py -q
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
  tests/test_api_task_execution.py -q
```

Expected: PASS
