# Failure-Aware Interview Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the reusable failure-aware interview runtime pattern in story mode so refinement uses the latest reusable draft instead of the latest attempt, transient failures support deterministic retry, user feedback survives failed calls, and save/delete/history behavior follows explicit projections.

**Architecture:** Introduce a generic JSON-serializable interview runtime helper in session state and route story generation through that helper instead of raw `story_attempts` / `story_outputs`. Keep story mode v1 on the current `UserStoryWriterOutput` schema contract (`user_stories` remains required), but structure attempt classification and draft kinds so clarification-only support can be added later without reworking the projection model. During rollout, legacy `story_attempts` and `story_outputs` remain derived compatibility mirrors only; all behavior reads the new projections.

**Tech Stack:** FastAPI, Pydantic, SQLModel-backed workflow session state, vanilla JavaScript frontend, pytest

---

## File Map

- Create: `services/interview_runtime.py`
  Responsibility: define reusable projection helpers for `(phase, subject_key)` runtime state, feedback thread storage, request snapshots, attempt recording, legacy story hydration, and reset behavior.
- Modify: `services/story_runtime.py`
  Responsibility: assemble story payloads from projections, classify story outcomes, expose frozen request snapshots for retry, and stop reading raw `story_attempts[-1]`.
- Modify: `api.py`
  Responsibility: make story endpoints projection-driven, add a dedicated retry endpoint, keep legacy state as derived mirrors, and update save/delete/history behavior.
- Modify: `frontend/project.js`
  Responsibility: consume projection-aware story API payloads, render attempt classifications/badges, gate save from `draft_projection`, and wire the `Retry same input` action.
- Modify: `frontend/project.html`
  Responsibility: add the retry button and any hint text needed for explicit retry vs. refine behavior.
- Create: `tests/test_interview_runtime.py`
  Responsibility: unit-test generic interview runtime helpers, migration, feedback absorption, and reset semantics.
- Modify: `tests/test_story_runtime.py`
  Responsibility: cover story payload assembly, reusable draft lookup, request replay, and failure classification.
- Create: `tests/test_api_story_interview_flow.py`
  Responsibility: cover projection-based story generate/history/retry/save behavior through the public API.
- Modify: `tests/test_api_delete_story.py`
  Responsibility: verify delete/reset clears the new working projections while preserving audit history markers.

### Task 1: Add Reusable Interview Runtime Projection Helpers

**Files:**
- Create: `/Users/aaat/projects/agileforge/services/interview_runtime.py`
- Create: `/Users/aaat/projects/agileforge/tests/test_interview_runtime.py`

- [ ] **Step 1: Write failing unit tests for subject initialization, feedback absorption, migration, and reset**

```python
from services import interview_runtime


def test_ensure_interview_subject_initializes_empty_projection():
    state = {}

    runtime = interview_runtime.ensure_interview_subject(
        state,
        phase="story",
        subject_key="Requirement A",
    )

    assert state["interview_runtime"]["story"]["Requirement A"] is runtime
    assert runtime["attempt_history"] == []
    assert runtime["draft_projection"] == {}
    assert runtime["feedback_projection"]["items"] == []
    assert runtime["request_projection"] == {}


def test_append_feedback_and_mark_absorbed():
    state = {}
    runtime = interview_runtime.ensure_interview_subject(
        state,
        phase="story",
        subject_key="Requirement A",
    )

    entry = interview_runtime.append_feedback_entry(
        runtime,
        text="Please narrow the scope to one release slice.",
        created_at="2026-03-28T12:00:00Z",
    )
    interview_runtime.mark_feedback_absorbed(
        runtime,
        feedback_ids=[entry["feedback_id"]],
        attempt_id="attempt-2",
    )

    stored = runtime["feedback_projection"]["items"][0]
    assert stored["status"] == "absorbed"
    assert stored["absorbed_by_attempt_id"] == "attempt-2"


def test_hydrate_story_runtime_from_legacy_attempts_promotes_latest_reusable_artifact():
    state = {
        "story_attempts": {
            "Requirement A": [
                {
                    "created_at": "2026-03-28T10:00:00Z",
                    "trigger": "manual_refine",
                    "input_context": {"requirement_context": "legacy-success"},
                    "output_artifact": {
                        "parent_requirement": "Requirement A",
                        "user_stories": [
                            {
                                "story_title": "Story A",
                                "statement": "As a developer, I want a reusable draft, so that I can refine it.",
                                "acceptance_criteria": ["Verify that the reusable draft survives migration."],
                                "invest_score": "High",
                                "estimated_effort": "S",
                                "produced_artifacts": [],
                            }
                        ],
                        "is_complete": True,
                        "clarifying_questions": [],
                    },
                    "is_complete": True,
                },
                {
                    "created_at": "2026-03-28T10:05:00Z",
                    "trigger": "manual_refine",
                    "input_context": {"requirement_context": "legacy-failure"},
                    "output_artifact": {
                        "error": "STORY_GENERATION_FAILED",
                        "message": "provider timeout",
                    },
                    "is_complete": False,
                    "failure_stage": "invocation_exception",
                },
            ]
        }
    }

    runtime = interview_runtime.hydrate_story_runtime_from_legacy(
        state,
        parent_requirement="Requirement A",
    )

    assert runtime["draft_projection"]["latest_reusable_attempt_id"] == "legacy-1"
    assert runtime["attempt_history"][-1]["classification"] == "nonreusable_provider_failure"


def test_reset_subject_working_set_clears_projections_and_keeps_audit_marker():
    state = {}
    runtime = interview_runtime.ensure_interview_subject(
        state,
        phase="story",
        subject_key="Requirement A",
    )
    runtime["attempt_history"].append({"attempt_id": "attempt-1"})
    runtime["draft_projection"] = {
        "latest_reusable_attempt_id": "attempt-1",
        "kind": "complete_draft",
        "is_complete": True,
        "updated_at": "2026-03-28T12:01:00Z",
    }
    runtime["request_projection"] = {
        "request_snapshot_id": "request-1",
        "payload": {"parent_requirement": "Requirement A"},
    }

    interview_runtime.reset_subject_working_set(
        runtime,
        created_at="2026-03-28T12:05:00Z",
        summary="Stories deleted and state reset by user.",
    )

    assert runtime["draft_projection"] == {}
    assert runtime["request_projection"] == {}
    assert runtime["attempt_history"][-1]["trigger"] == "reset"
    assert runtime["attempt_history"][-1]["summary"] == "Stories deleted and state reset by user."
```

- [ ] **Step 2: Run the new projection-helper tests to verify they fail**

Run: `pytest tests/test_interview_runtime.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'services.interview_runtime'`.

- [ ] **Step 3: Create `services/interview_runtime.py` with the generic projection helpers**

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


def ensure_interview_subject(
    state: Dict[str, Any],
    *,
    phase: str,
    subject_key: str,
) -> Dict[str, Any]:
    runtime_root = state.setdefault("interview_runtime", {})
    phase_root = runtime_root.setdefault(phase, {})
    subject = phase_root.setdefault(
        subject_key,
        {
            "attempt_history": [],
            "draft_projection": {},
            "feedback_projection": {"items": []},
            "request_projection": {},
        },
    )
    subject.setdefault("attempt_history", [])
    subject.setdefault("draft_projection", {})
    subject.setdefault("feedback_projection", {"items": []})
    subject["feedback_projection"].setdefault("items", [])
    subject.setdefault("request_projection", {})
    return subject


def append_feedback_entry(
    runtime: Dict[str, Any],
    *,
    text: str,
    created_at: str,
    feedback_id: Optional[str] = None,
) -> Dict[str, Any]:
    entry = {
        "feedback_id": feedback_id or f"feedback-{len(runtime['feedback_projection']['items']) + 1}",
        "text": text,
        "created_at": created_at,
        "status": "unabsorbed",
        "absorbed_by_attempt_id": None,
    }
    runtime["feedback_projection"]["items"].append(entry)
    return entry


def mark_feedback_absorbed(
    runtime: Dict[str, Any],
    *,
    feedback_ids: List[str],
    attempt_id: str,
) -> None:
    wanted = set(feedback_ids)
    for item in runtime["feedback_projection"]["items"]:
        if item["feedback_id"] in wanted:
            item["status"] = "absorbed"
            item["absorbed_by_attempt_id"] = attempt_id


def set_request_projection(
    runtime: Dict[str, Any],
    *,
    request_snapshot_id: str,
    payload: Dict[str, Any],
    request_hash: str,
    created_at: str,
    draft_basis_attempt_id: Optional[str],
    included_feedback_ids: List[str],
    context_version: str,
) -> Dict[str, Any]:
    runtime["request_projection"] = {
        "request_snapshot_id": request_snapshot_id,
        "payload": deepcopy(payload),
        "request_hash": request_hash,
        "created_at": created_at,
        "draft_basis_attempt_id": draft_basis_attempt_id,
        "included_feedback_ids": list(included_feedback_ids),
        "context_version": context_version,
    }
    return runtime["request_projection"]
```

- [ ] **Step 4: Add attempt-recording, legacy hydration, and reset helpers**

```python
def append_attempt(runtime: Dict[str, Any], attempt: Dict[str, Any]) -> Dict[str, Any]:
    runtime["attempt_history"].append(attempt)
    return attempt


def promote_reusable_draft(
    runtime: Dict[str, Any],
    *,
    attempt_id: str,
    kind: str,
    is_complete: bool,
    updated_at: str,
) -> None:
    runtime["draft_projection"] = {
        "latest_reusable_attempt_id": attempt_id,
        "kind": kind,
        "is_complete": is_complete,
        "updated_at": updated_at,
    }


def reset_subject_working_set(
    runtime: Dict[str, Any],
    *,
    created_at: str,
    summary: str,
) -> None:
    runtime["draft_projection"] = {}
    runtime["request_projection"] = {}
    runtime["feedback_projection"] = {"items": []}
    runtime["attempt_history"].append(
        {
            "attempt_id": f"reset-{len(runtime['attempt_history']) + 1}",
            "created_at": created_at,
            "trigger": "reset",
            "classification": "reset_marker",
            "is_reusable": False,
            "retryable": False,
            "summary": summary,
            "output_artifact": None,
        }
    )


def hydrate_story_runtime_from_legacy(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
) -> Dict[str, Any]:
    runtime = ensure_interview_subject(
        state,
        phase="story",
        subject_key=parent_requirement,
    )
    if runtime["attempt_history"]:
        return runtime

    legacy_attempts = (state.get("story_attempts") or {}).get(parent_requirement, [])
    for index, attempt in enumerate(legacy_attempts, start=1):
        attempt_id = f"legacy-{index}"
        output_artifact = attempt.get("output_artifact") or {}
        is_reusable = bool(
            isinstance(output_artifact, dict)
            and output_artifact.get("user_stories")
            and not output_artifact.get("error")
        )
        classification = (
            "reusable_content_result"
            if is_reusable
            else (
                "nonreusable_provider_failure"
                if attempt.get("failure_stage") == "invocation_exception"
                else "nonreusable_schema_failure"
            )
        )
        runtime["attempt_history"].append(
            {
                "attempt_id": attempt_id,
                "created_at": attempt.get("created_at"),
                "trigger": attempt.get("trigger"),
                "classification": classification,
                "is_reusable": is_reusable,
                "retryable": False,
                "output_artifact": output_artifact,
            }
        )
        if is_reusable:
            promote_reusable_draft(
                runtime,
                attempt_id=attempt_id,
                kind="complete_draft" if attempt.get("is_complete") else "incomplete_draft",
                is_complete=bool(attempt.get("is_complete")),
                updated_at=attempt.get("created_at", ""),
            )

    return runtime
```

- [ ] **Step 5: Re-run the projection-helper tests**

Run: `pytest tests/test_interview_runtime.py -q`

Expected: PASS

- [ ] **Step 6: Commit the reusable interview runtime helpers**

```bash
git add services/interview_runtime.py tests/test_interview_runtime.py
git commit -m "feat: add interview runtime projection helpers"
```

### Task 2: Refactor Story Runtime to Assemble Requests From Projections

**Files:**
- Modify: `/Users/aaat/projects/agileforge/services/story_runtime.py`
- Modify: `/Users/aaat/projects/agileforge/tests/test_story_runtime.py`

- [ ] **Step 1: Expand story runtime tests to cover reusable draft lookup, request replay, and failure classification**

```python
from __future__ import annotations

import json

import pytest

from services import story_runtime


def _valid_story_output(parent_requirement: str, *, is_complete: bool = True) -> str:
    return json.dumps(
        {
            "parent_requirement": parent_requirement,
            "user_stories": [
                {
                    "story_title": "Valid story",
                    "statement": "As a developer, I want a valid story, so that I can proceed.",
                    "acceptance_criteria": ["Verify that the story is valid."],
                    "invest_score": "High",
                    "estimated_effort": "S",
                    "produced_artifacts": [],
                }
            ],
            "is_complete": is_complete,
            "clarifying_questions": [] if is_complete else ["Need more detail"],
        }
    )


@pytest.mark.asyncio
async def test_story_runtime_uses_latest_reusable_draft_projection(monkeypatch) -> None:
    captured = {}

    async def fake_invoke(payload):
        captured["payload"] = payload
        return _valid_story_output(payload.parent_requirement)

    monkeypatch.setattr(story_runtime, "_invoke_story_agent", fake_invoke)

    state = {
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "classification": "reusable_content_result",
                            "output_artifact": {
                                "parent_requirement": "Requirement A",
                                "user_stories": [
                                    {
                                        "story_title": "Reusable story",
                                        "statement": "As a developer, I want a reusable draft, so that I can refine it.",
                                        "acceptance_criteria": ["Verify that the reusable draft is injected."],
                                        "invest_score": "High",
                                        "estimated_effort": "S",
                                        "produced_artifacts": [],
                                    }
                                ],
                                "is_complete": True,
                                "clarifying_questions": [],
                            },
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                    },
                    "feedback_projection": {
                        "items": [
                            {
                                "feedback_id": "feedback-1",
                                "text": "Please narrow the scope.",
                                "status": "unabsorbed",
                                "absorbed_by_attempt_id": None,
                            }
                        ]
                    },
                    "request_projection": {},
                }
            }
        },
    }

    result = await story_runtime.run_story_agent_from_state(
        state,
        project_id=1,
        parent_requirement="Requirement A",
        user_input=None,
    )

    assert result["classification"] == "reusable_content_result"
    assert "--- PREVIOUS DRAFT TO REFINE ---" in captured["payload"].requirement_context
    assert "Please narrow the scope." in captured["payload"].requirement_context


@pytest.mark.asyncio
async def test_story_runtime_invalid_json_is_nonreusable_schema_failure(monkeypatch) -> None:
    async def fake_invoke(_payload):
        return '{"broken": '

    monkeypatch.setattr(story_runtime, "_invoke_story_agent", fake_invoke)

    result = await story_runtime.run_story_agent_from_state(
        {
            "pending_spec_content": "SPEC",
            "compiled_authority_cached": '{"ok": true}',
        },
        project_id=1,
        parent_requirement="Requirement A",
        user_input="retry",
    )

    assert result["classification"] == "nonreusable_schema_failure"
    assert result["is_reusable"] is False
    assert result["draft_kind"] is None


@pytest.mark.asyncio
async def test_story_runtime_replay_uses_frozen_request_payload(monkeypatch) -> None:
    captured = {}

    async def fake_invoke(payload):
        captured["payload"] = payload
        return _valid_story_output(payload.parent_requirement)

    monkeypatch.setattr(story_runtime, "_invoke_story_agent", fake_invoke)

    result = await story_runtime.run_story_agent_request(
        {
            "parent_requirement": "Requirement A",
            "requirement_context": "Frozen request payload",
            "technical_spec": "SPEC",
            "compiled_authority": '{"ok": true}',
            "global_roadmap_context": "",
            "already_generated_milestone_stories": "",
            "artifact_registry": {},
        },
        project_id=1,
        parent_requirement="Requirement A",
    )

    assert result["classification"] == "reusable_content_result"
    assert captured["payload"].requirement_context == "Frozen request payload"
```

- [ ] **Step 2: Run the story runtime tests to verify they fail**

Run: `pytest tests/test_story_runtime.py -q`

Expected: FAIL because `run_story_agent_from_state` still reads raw `story_attempts`, `run_story_agent_request` does not exist, and the result payload has no `classification` / `draft_kind`.

- [ ] **Step 3: Add projection-aware request building and frozen request replay to `services/story_runtime.py`**

```python
from services.interview_runtime import ensure_interview_subject


def _get_latest_reusable_story_artifact(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
) -> Optional[Dict[str, Any]]:
    runtime = ensure_interview_subject(
        state,
        phase="story",
        subject_key=parent_requirement,
    )
    draft_projection = runtime.get("draft_projection") or {}
    attempt_id = draft_projection.get("latest_reusable_attempt_id")
    if not attempt_id:
        return None

    for attempt in reversed(runtime.get("attempt_history") or []):
        if attempt.get("attempt_id") == attempt_id:
            artifact = attempt.get("output_artifact")
            return artifact if isinstance(artifact, dict) else None
    return None


def _collect_unabsorbed_feedback_text(runtime: Dict[str, Any]) -> List[str]:
    items = runtime.get("feedback_projection", {}).get("items", [])
    return [item["text"] for item in items if item.get("status") == "unabsorbed" and item.get("text")]


def build_story_request_payload(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
) -> Dict[str, Any]:
    input_context = build_story_input_context(state, parent_requirement=parent_requirement)
    runtime = ensure_interview_subject(
        state,
        phase="story",
        subject_key=parent_requirement,
    )

    reusable_artifact = _get_latest_reusable_story_artifact(
        state,
        parent_requirement=parent_requirement,
    )
    if reusable_artifact:
        input_context["requirement_context"] += (
            "\n\n--- PREVIOUS DRAFT TO REFINE ---\n"
            f"{json.dumps(reusable_artifact, indent=2)}"
        )

    feedback_items = _collect_unabsorbed_feedback_text(runtime)
    if feedback_items:
        input_context["requirement_context"] += (
            "\n\n--- USER REFINEMENT FEEDBACK ---\n"
            + "\n".join(feedback_items)
        )

    return input_context


async def run_story_agent_request(
    request_payload: Dict[str, Any],
    *,
    project_id: int,
    parent_requirement: str,
) -> Dict[str, Any]:
    payload = UserStoryWriterInput.model_validate(request_payload)
    raw_text = await _invoke_story_agent(payload)
    parsed = parse_json_payload(raw_text)
    if parsed is None:
        return {
            **_failure(
                project_id=project_id,
                parent_requirement=parent_requirement,
                input_context=request_payload,
                failure_stage="invalid_json",
                message="Story response is not valid JSON",
                raw_text=raw_text,
            ),
            "classification": "nonreusable_schema_failure",
            "draft_kind": None,
            "is_reusable": False,
            "request_payload": request_payload,
        }

    output_model = UserStoryWriterOutput.model_validate(parsed)
    output_artifact = output_model.model_dump(exclude_none=True)
    return {
        "success": True,
        "input_context": request_payload,
        "output_artifact": output_artifact,
        "classification": "reusable_content_result",
        "draft_kind": "complete_draft" if output_artifact.get("is_complete") else "incomplete_draft",
        "is_reusable": True,
        "is_complete": bool(output_artifact.get("is_complete", False)),
        "request_payload": request_payload,
        "failure_artifact_id": None,
        "failure_stage": None,
        "failure_summary": None,
        "raw_output_preview": None,
        "has_full_artifact": False,
    }
```

- [ ] **Step 4: Make `run_story_agent_from_state` a projection-based wrapper and classify failures explicitly**

```python
async def run_story_agent_from_state(
    state: Dict[str, Any],
    *,
    project_id: int,
    parent_requirement: str,
    user_input: Optional[str],
) -> Dict[str, Any]:
    request_payload = build_story_request_payload(
        state,
        parent_requirement=parent_requirement,
    )
    try:
        return await run_story_agent_request(
            request_payload,
            project_id=project_id,
            parent_requirement=parent_requirement,
        )
    except AgentInvocationError as exc:
        failed = _failure(
            project_id=project_id,
            parent_requirement=parent_requirement,
            input_context=request_payload,
            failure_stage="invocation_exception",
            message=f"Story runtime failed: {exc}",
            raw_text=exc.partial_output,
            exception=exc,
        )
        failed.update(
            {
                "classification": "nonreusable_provider_failure",
                "draft_kind": None,
                "is_reusable": False,
                "request_payload": request_payload,
            }
        )
        return failed
    except ValidationError as exc:
        failed = _failure(
            project_id=project_id,
            parent_requirement=parent_requirement,
            input_context=request_payload,
            failure_stage="output_validation",
            message=f"Story output validation failed: {exc}",
            validation_errors=exc.errors(),
            exception=exc,
        )
        failed.update(
            {
                "classification": "nonreusable_schema_failure",
                "draft_kind": None,
                "is_reusable": False,
                "request_payload": request_payload,
            }
        )
        return failed
```

- [ ] **Step 5: Re-run the story runtime tests**

Run: `pytest tests/test_story_runtime.py -q`

Expected: PASS

- [ ] **Step 6: Commit the projection-aware story runtime**

```bash
git add services/story_runtime.py tests/test_story_runtime.py
git commit -m "feat: make story runtime projection-aware"
```

### Task 3: Make Story API Endpoints Projection-Driven and Add Explicit Retry

**Files:**
- Modify: `/Users/aaat/projects/agileforge/api.py`
- Create: `/Users/aaat/projects/agileforge/tests/test_api_story_interview_flow.py`
- Modify: `/Users/aaat/projects/agileforge/tests/test_api_delete_story.py`

- [ ] **Step 1: Write failing API tests for projection-based generate, retry, save, and history**

```python
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient

import api as api_module


@dataclass
class DummyProduct:
    product_id: int
    name: str
    description: Optional[str] = None


class DummyProductRepository:
    def __init__(self) -> None:
        self.products = []

    def get_by_id(self, product_id: int):
        return next((p for p in self.products if p.product_id == product_id), None)

    def create(self, name: str):
        product = DummyProduct(product_id=len(self.products) + 1, name=name)
        self.products.append(product)
        return product


class DummyWorkflowService:
    def __init__(self) -> None:
        self.states: Dict[str, Dict[str, Any]] = {}

    async def initialize_session(self, session_id: Optional[str] = None) -> str:
        sid = str(session_id or "generated")
        self.states[sid] = {"fsm_state": "STORY_INTERVIEW"}
        return sid

    def get_session_status(self, session_id: str):
        return dict(self.states.get(str(session_id), {}))

    def update_session_status(self, session_id: str, partial_update):
        current = dict(self.states.get(str(session_id), {}))
        current.update(partial_update)
        self.states[str(session_id)] = current

    def migrate_legacy_setup_state(self) -> int:
        return 0


def _build_client(monkeypatch):
    repo = DummyProductRepository()
    workflow = DummyWorkflowService()
    monkeypatch.setattr(api_module, "product_repo", repo)
    monkeypatch.setattr(api_module, "workflow_service", workflow)
    return TestClient(api_module.app), repo, workflow


def test_story_generate_promotes_reusable_draft_and_absorbs_feedback(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "roadmap_releases": [{"items": ["Requirement A"]}],
    }

    async def fake_run_story_agent_from_state(state, *, project_id, parent_requirement, user_input):
        return {
            "success": True,
            "input_context": {"requirement_context": "assembled"},
            "output_artifact": {
                "parent_requirement": parent_requirement,
                "user_stories": [
                    {
                        "story_title": "Story A",
                        "statement": "As a developer, I want a saved draft, so that I can persist it.",
                        "acceptance_criteria": ["Verify that save uses the reusable draft."],
                        "invest_score": "High",
                        "estimated_effort": "S",
                        "produced_artifacts": [],
                    }
                ],
                "is_complete": True,
                "clarifying_questions": [],
            },
            "classification": "reusable_content_result",
            "draft_kind": "complete_draft",
            "is_reusable": True,
            "is_complete": True,
            "request_payload": {
                "parent_requirement": parent_requirement,
                "requirement_context": "assembled",
                "technical_spec": "SPEC",
                "compiled_authority": '{"ok": true}',
                "global_roadmap_context": "",
                "already_generated_milestone_stories": "",
                "artifact_registry": {},
            },
            "failure_artifact_id": None,
            "failure_stage": None,
            "failure_summary": None,
            "raw_output_preview": None,
            "has_full_artifact": False,
        }

    monkeypatch.setattr(api_module, "run_story_agent_from_state", fake_run_story_agent_from_state)

    response = client.post(
        f"/api/projects/{product.product_id}/story/generate",
        params={"parent_requirement": "Requirement A"},
        json={"user_input": "Please keep this to one milestone."},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["retry"]["available"] is False
    assert payload["save"]["available"] is True
    runtime = workflow.states[str(product.product_id)]["interview_runtime"]["story"]["Requirement A"]
    assert runtime["draft_projection"]["kind"] == "complete_draft"
    assert runtime["feedback_projection"]["items"][0]["status"] == "absorbed"


def test_story_retry_replays_frozen_request_and_preserves_good_draft(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "roadmap_releases": [{"items": ["Requirement A"]}],
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "output_artifact": {
                                "parent_requirement": "Requirement A",
                                "user_stories": [
                                    {
                                        "story_title": "Saved draft",
                                        "statement": "As a developer, I want a saved draft, so that I can retry around failures.",
                                        "acceptance_criteria": ["Verify that the saved draft survives failed retries."],
                                        "invest_score": "High",
                                        "estimated_effort": "S",
                                        "produced_artifacts": [],
                                    }
                                ],
                                "is_complete": True,
                                "clarifying_questions": [],
                            },
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                    },
                    "feedback_projection": {"items": []},
                    "request_projection": {
                        "request_snapshot_id": "request-2",
                        "payload": {
                            "parent_requirement": "Requirement A",
                            "requirement_context": "frozen",
                            "technical_spec": "SPEC",
                            "compiled_authority": '{"ok": true}',
                            "global_roadmap_context": "",
                            "already_generated_milestone_stories": "",
                            "artifact_registry": {},
                        },
                    },
                }
            }
        },
    }

    async def fake_retry(request_payload, *, project_id, parent_requirement):
        assert request_payload["requirement_context"] == "frozen"
        return {
            "success": False,
            "input_context": request_payload,
            "output_artifact": {"error": "STORY_GENERATION_FAILED", "message": "provider timeout"},
            "classification": "nonreusable_provider_failure",
            "draft_kind": None,
            "is_reusable": False,
            "is_complete": None,
            "request_payload": request_payload,
            "failure_artifact_id": "story-failure-1",
            "failure_stage": "invocation_exception",
            "failure_summary": "provider timeout",
            "raw_output_preview": None,
            "has_full_artifact": True,
        }

    monkeypatch.setattr(api_module, "run_story_agent_request", fake_retry)

    response = client.post(
        f"/api/projects/{product.product_id}/story/retry",
        params={"parent_requirement": "Requirement A"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["retry"]["available"] is True
    runtime = workflow.states[str(product.product_id)]["interview_runtime"]["story"]["Requirement A"]
    assert runtime["draft_projection"]["latest_reusable_attempt_id"] == "attempt-1"


def test_story_save_uses_complete_reusable_draft_not_latest_failed_attempt(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "output_artifact": {
                                "parent_requirement": "Requirement A",
                                "user_stories": [
                                    {
                                        "story_title": "Saved draft",
                                        "statement": "As a developer, I want a complete reusable draft, so that save still works.",
                                        "acceptance_criteria": ["Verify that save reads the reusable draft projection."],
                                        "invest_score": "High",
                                        "estimated_effort": "S",
                                        "produced_artifacts": [],
                                    }
                                ],
                                "is_complete": True,
                                "clarifying_questions": [],
                            },
                        },
                        {
                            "attempt_id": "attempt-2",
                            "classification": "nonreusable_provider_failure",
                            "is_reusable": False,
                            "retryable": True,
                            "output_artifact": {"error": "STORY_GENERATION_FAILED", "message": "provider timeout"},
                        },
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                    },
                    "feedback_projection": {"items": []},
                    "request_projection": {},
                }
            }
        },
    }

    def fake_save_stories_tool(save_input, _context):
        assert save_input.parent_requirement == "Requirement A"
        assert len(save_input.stories) == 1
        return {"success": True, "saved_count": 1}

    monkeypatch.setattr(api_module, "save_stories_tool", fake_save_stories_tool)

    response = client.post(
        f"/api/projects/{product.product_id}/story/save",
        params={"parent_requirement": "Requirement A"},
    )

    assert response.status_code == 200
```

- [ ] **Step 2: Run the story interview API tests to verify they fail**

Run: `pytest tests/test_api_story_interview_flow.py tests/test_api_delete_story.py -q`

Expected: FAIL because story endpoints still read `story_attempts` / `story_outputs`, there is no `/story/retry` endpoint, and delete does not clear the new projections.

- [ ] **Step 3: Refactor `api.py` to persist story interview state through `interview_runtime`**

```python
from services.interview_runtime import (
    append_attempt,
    append_feedback_entry,
    ensure_interview_subject,
    mark_feedback_absorbed,
    promote_reusable_draft,
    reset_subject_working_set,
    set_request_projection,
)


def _find_attempt_by_id(runtime: Dict[str, Any], attempt_id: str) -> Optional[Dict[str, Any]]:
    for attempt in reversed(runtime.get("attempt_history") or []):
        if attempt.get("attempt_id") == attempt_id:
            return attempt
    return None


def _story_interview_summary(runtime: Dict[str, Any]) -> Dict[str, Any]:
    draft_projection = runtime.get("draft_projection") or {}
    latest_attempt = (runtime.get("attempt_history") or [{}])[-1]
    request_projection = runtime.get("request_projection") or {}
    retry_available = bool(
        latest_attempt.get("retryable")
        and request_projection.get("payload")
    )
    return {
        "current_draft": {
            "attempt_id": draft_projection.get("latest_reusable_attempt_id"),
            "kind": draft_projection.get("kind"),
            "is_complete": bool(draft_projection.get("is_complete", False)),
        } if draft_projection else None,
        "retry": {
            "available": retry_available,
            "target_attempt_id": latest_attempt.get("attempt_id") if retry_available else None,
        },
        "save": {
            "available": bool(_story_save_payload(runtime)),
        },
    }


def _story_save_payload(runtime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    draft_projection = runtime.get("draft_projection") or {}
    if draft_projection.get("kind") != "complete_draft":
        return None

    attempt = _find_attempt_by_id(
        runtime,
        draft_projection.get("latest_reusable_attempt_id", ""),
    )
    artifact = (attempt or {}).get("output_artifact") or {}
    if not artifact.get("is_complete"):
        return None
    return artifact
```

- [ ] **Step 4: Add projection-aware generate/retry/history/save/delete endpoint behavior**

```python
@app.post("/api/projects/{project_id}/story/retry")
async def retry_project_story(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    runtime = ensure_interview_subject(
        state,
        phase="story",
        subject_key=parent_requirement,
    )
    request_projection = runtime.get("request_projection") or {}
    request_payload = request_projection.get("payload")
    if not isinstance(request_payload, dict):
        raise HTTPException(status_code=409, detail="No replayable story request is available.")

    story_result = await story_runtime.run_story_agent_request(
        request_payload,
        project_id=project_id,
        parent_requirement=parent_requirement,
    )
    attempt_id = f"attempt-{len(runtime['attempt_history']) + 1}"
    append_attempt(
        runtime,
        {
            "attempt_id": attempt_id,
            "created_at": _now_iso(),
            "trigger": "retry_same_input",
            "request_snapshot_id": request_projection["request_snapshot_id"],
            "draft_basis_attempt_id": request_projection.get("draft_basis_attempt_id"),
            "included_feedback_ids": list(request_projection.get("included_feedback_ids") or []),
            "classification": story_result["classification"],
            "is_reusable": story_result["is_reusable"],
            "retryable": story_result["classification"] in {"nonreusable_transport_failure", "nonreusable_provider_failure"},
            "draft_kind": story_result.get("draft_kind"),
            "output_artifact": story_result.get("output_artifact") or {},
            **_failure_meta(story_result, fallback_summary=story_result.get("error")),
        },
    )
    if story_result["is_reusable"]:
        promote_reusable_draft(
            runtime,
            attempt_id=attempt_id,
            kind=story_result["draft_kind"],
            is_complete=bool(story_result.get("is_complete")),
            updated_at=_now_iso(),
        )
        mark_feedback_absorbed(
            runtime,
            feedback_ids=list(request_projection.get("included_feedback_ids") or []),
            attempt_id=attempt_id,
        )
    _sync_story_legacy_mirrors(
        state,
        parent_requirement=parent_requirement,
        runtime=runtime,
    )
    _save_session_state(session_id, state)
    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "output_artifact": story_result.get("output_artifact"),
            **_story_interview_summary(runtime),
        },
    }
```

```python
runtime = ensure_interview_subject(
    state,
    phase="story",
    subject_key=parent_requirement,
)
new_feedback_ids = []
if req.user_input and req.user_input.strip():
    entry = append_feedback_entry(
        runtime,
        text=req.user_input.strip(),
        created_at=_now_iso(),
    )
    new_feedback_ids.append(entry["feedback_id"])

story_result = await run_story_agent_from_state(
    state,
    project_id=project_id,
    parent_requirement=parent_requirement,
    user_input=req.user_input,
)
request_projection = set_request_projection(
    runtime,
    request_snapshot_id=f"request-{len(runtime['attempt_history']) + 1}",
    payload=story_result["request_payload"],
    request_hash=hashlib.sha256(
        json.dumps(story_result["request_payload"], sort_keys=True).encode("utf-8")
    ).hexdigest(),
    created_at=_now_iso(),
    draft_basis_attempt_id=(runtime.get("draft_projection") or {}).get("latest_reusable_attempt_id"),
    included_feedback_ids=new_feedback_ids,
    context_version="story-runtime.v1",
)
attempt_id = f"attempt-{len(runtime['attempt_history']) + 1}"
append_attempt(
    runtime,
    {
        "attempt_id": attempt_id,
        "created_at": _now_iso(),
        "trigger": "manual_refine" if req.user_input else "auto_transition",
        "request_snapshot_id": request_projection["request_snapshot_id"],
        "draft_basis_attempt_id": request_projection["draft_basis_attempt_id"],
        "included_feedback_ids": list(new_feedback_ids),
        "classification": story_result["classification"],
        "is_reusable": story_result["is_reusable"],
        "retryable": story_result["classification"] in {"nonreusable_transport_failure", "nonreusable_provider_failure"},
        "draft_kind": story_result.get("draft_kind"),
        "output_artifact": story_result.get("output_artifact") or {},
        **_failure_meta(story_result, fallback_summary=story_result.get("error")),
    },
)
if story_result["is_reusable"]:
    promote_reusable_draft(
        runtime,
        attempt_id=attempt_id,
        kind=story_result["draft_kind"],
        is_complete=bool(story_result.get("is_complete")),
        updated_at=_now_iso(),
    )
    mark_feedback_absorbed(
        runtime,
        feedback_ids=new_feedback_ids,
        attempt_id=attempt_id,
    )
_sync_story_legacy_mirrors(
    state,
    parent_requirement=parent_requirement,
    runtime=runtime,
)
_save_session_state(session_id, state)
return {
    "status": "success",
    "parent_requirement": parent_requirement,
    "data": {
        "output_artifact": story_result.get("output_artifact"),
        **_story_interview_summary(runtime),
    },
}
```

- [ ] **Step 5: Keep legacy mirrors derived from the new runtime and update delete behavior**

```python
def _sync_story_legacy_mirrors(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
    runtime: Dict[str, Any],
) -> None:
    story_attempts = state.setdefault("story_attempts", {})
    story_attempts[parent_requirement] = [
        {
            "created_at": attempt.get("created_at"),
            "trigger": attempt.get("trigger"),
            "input_context": {},
            "output_artifact": attempt.get("output_artifact"),
            "is_complete": bool((attempt.get("output_artifact") or {}).get("is_complete")),
            "failure_artifact_id": attempt.get("failure_artifact_id"),
            "failure_stage": attempt.get("failure_stage"),
            "failure_summary": attempt.get("failure_summary"),
            "raw_output_preview": attempt.get("raw_output_preview"),
            "has_full_artifact": attempt.get("has_full_artifact", False),
        }
        for attempt in runtime.get("attempt_history") or []
        if attempt.get("trigger") != "reset"
    ]

    story_outputs = state.setdefault("story_outputs", {})
    reusable = _story_save_payload(runtime)
    if reusable:
        story_outputs[parent_requirement] = reusable
    else:
        story_outputs.pop(parent_requirement, None)
```

```python
runtime = ensure_interview_subject(
    state,
    phase="story",
    subject_key=parent_requirement,
)
reset_subject_working_set(
    runtime,
    created_at=_now_iso(),
    summary="Stories deleted and state reset by user.",
)
state.get("story_saved", {}).pop(parent_requirement, None)
state.get("story_outputs", {}).pop(parent_requirement, None)
_sync_story_legacy_mirrors(
    state,
    parent_requirement=parent_requirement,
    runtime=runtime,
)
```

```python
@app.get("/api/projects/{project_id}/story/history")
async def get_project_story_history(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    runtime = ensure_interview_subject(
        state,
        phase="story",
        subject_key=parent_requirement,
    )

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "items": runtime.get("attempt_history", []),
            "count": len(runtime.get("attempt_history", [])),
            **_story_interview_summary(runtime),
        },
    }
```

- [ ] **Step 6: Re-run the story interview API tests**

Run: `pytest tests/test_api_story_interview_flow.py tests/test_api_delete_story.py -q`

Expected: PASS

- [ ] **Step 7: Commit the projection-driven story API**

```bash
git add api.py tests/test_api_story_interview_flow.py tests/test_api_delete_story.py
git commit -m "feat: add failure-aware story interview api"
```

### Task 4: Update Story Interview UI for Explicit Retry and Projection-Based Save

**Files:**
- Modify: `/Users/aaat/projects/agileforge/frontend/project.html`
- Modify: `/Users/aaat/projects/agileforge/frontend/project.js`

- [ ] **Step 1: Add the explicit retry button to the story action bar**

```html
<div class="flex gap-3">
    <button id="btn-generate-story"
        onclick="generateStoryDraft()"
        class="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-orange-600 hover:bg-orange-700 text-white font-bold transition-all shadow-sm">
        <span class="material-symbols-outlined text-sm">cycle</span>
        Generate / Refine
    </button>
    <button id="btn-retry-story"
        onclick="retryStoryDraft()"
        class="hidden inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-white font-bold transition-all shadow-sm">
        <span class="material-symbols-outlined text-sm">refresh</span>
        Retry same input
    </button>
</div>
```

- [ ] **Step 2: Track projection-driven UI state in `frontend/project.js`**

```javascript
let activeStoryAttemptCount = 0;
let activeStoryIsComplete = false;
let activeStoryRetryAvailable = false;
let activeStoryRetryTargetAttemptId = null;
let activeStorySaveAvailable = false;
let activeStoryDraftKind = null;

function applyStoryProjectionState(payload) {
    const draft = payload.current_draft || null;
    const retry = payload.retry || { available: false, target_attempt_id: null };
    const save = payload.save || { available: false };

    activeStoryDraftKind = draft?.kind || null;
    activeStoryIsComplete = Boolean(draft?.is_complete);
    activeStoryRetryAvailable = Boolean(retry.available);
    activeStoryRetryTargetAttemptId = retry.target_attempt_id || null;
    activeStorySaveAvailable = Boolean(save.available);
}
```

- [ ] **Step 3: Render history badges from classification and gate save/retry from projections**

```javascript
function renderStoryHistory(items) {
    const container = document.getElementById('story-history-list');
    if (!container) return;

    container.innerHTML = '';
    if (!items || items.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No attempts yet.</p>';
        return;
    }

    const badgeMeta = {
        reusable_content_result: ['Reusable draft', 'text-emerald-600 bg-emerald-50 ring-emerald-200'],
        nonreusable_provider_failure: ['Retryable failure', 'text-slate-700 bg-slate-100 ring-slate-200'],
        nonreusable_transport_failure: ['Retryable failure', 'text-slate-700 bg-slate-100 ring-slate-200'],
        nonreusable_schema_failure: ['Schema failure', 'text-red-700 bg-red-50 ring-red-200'],
        reset_marker: ['Reset', 'text-amber-700 bg-amber-50 ring-amber-200'],
    };

    [...items].reverse().forEach((item, index) => {
        const [label, color] = badgeMeta[item.classification] || ['Attempt', 'text-amber-600 bg-amber-50 ring-amber-200'];
        const row = document.createElement('div');
        row.className = 'border border-slate-200 dark:border-slate-700 rounded-lg p-3 bg-slate-50 dark:bg-slate-800/60 transition-transform';
        row.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-xs font-extrabold text-slate-700 dark:text-slate-300">Attempt ${items.length - index}</span>
                <span class="text-[10px] uppercase ${color} px-2 py-0.5 rounded-full ring-1 ring-inset font-bold">${label}</span>
            </div>
            <p class="text-[10px] text-slate-400 mt-2">${item.created_at || '-'}</p>
        `;
        container.appendChild(row);
    });
}

function updateStorySaveButton() {
    const button = document.getElementById('btn-save-story');
    const retryButton = document.getElementById('btn-retry-story');
    const hint = document.getElementById('story-save-hint');
    if (!button || !hint || !retryButton) return;

    button.disabled = !activeStorySaveAvailable;
    retryButton.classList.toggle('hidden', !activeStoryRetryAvailable);
    hint.innerText = activeStorySaveAvailable
        ? 'Reusable complete draft is ready to save.'
        : activeStoryRetryAvailable
            ? 'Latest attempt failed without replacing the reusable draft. Retry the same input or keep refining.'
            : 'Save disabled until a complete reusable draft exists.';
}
```

- [ ] **Step 4: Wire the new retry endpoint and projection-aware history payload**

```javascript
async function loadStoryHistory(reqName) {
    if (!reqName || !selectedProjectId) return;

    const response = await fetch(`/api/projects/${selectedProjectId}/story/history?parent_requirement=${encodeURIComponent(reqName)}`);
    const data = await response.json();
    const payload = data.data || {};
    const items = Array.isArray(payload.items) ? payload.items : [];

    activeStoryAttemptCount = items.length;
    applyStoryProjectionState(payload);
    renderStoryHistory(items);

    if (items.length > 0) {
        const latest = items[items.length - 1];
        renderStoryAttemptPanels(latest.input_context || null, latest.output_artifact || null);
    } else {
        renderStoryAttemptPanels(null, null);
    }
    updateStorySaveButton();
}


async function retryStoryDraft() {
    if (!selectedProjectId || !activeStoryReq || !activeStoryRetryAvailable) return;

    const button = document.getElementById('btn-retry-story');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">refresh</span> Retrying...';
        button.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/story/retry?parent_requirement=${encodeURIComponent(activeStoryReq)}`, {
            method: 'POST',
        });
        if (response.status >= 400) {
            const body = await response.json();
            throw new Error(body.detail || 'Retry failed.');
        }
        await loadStoryRequirements();
        await loadStoryHistory(activeStoryReq);
    } catch (error) {
        alert(error.message || 'Retry failed.');
    } finally {
        if (button) {
            button.innerHTML = original || '<span class="material-symbols-outlined text-sm">refresh</span> Retry same input';
            button.disabled = false;
        }
    }
}

window.retryStoryDraft = retryStoryDraft;
```

- [ ] **Step 5: Run the backend regression suite after the frontend wiring**

Run: `pytest tests/test_interview_runtime.py tests/test_story_runtime.py tests/test_api_story_interview_flow.py tests/test_api_delete_story.py -q`

Expected: PASS

- [ ] **Step 6: Manual smoke-test the story phase in the browser**

Run: `uvicorn api:app --reload`

Expected: FastAPI starts and serves `http://127.0.0.1:8000/dashboard`.

Manual checks:
- Open an existing project already in story mode.
- Generate a successful story draft and confirm the save hint reads `Reusable complete draft is ready to save.`
- Force a retryable story failure and confirm `Retry same input` appears while save remains enabled from the earlier reusable draft.
- Click `Retry same input` and confirm the latest attempt updates without duplicating the feedback text in the textarea.
- Delete the story draft and confirm the retry button disappears, save disables, and the history shows a reset marker.

- [ ] **Step 7: Commit the projection-aware story UI**

```bash
git add frontend/project.html frontend/project.js
git commit -m "feat: add explicit retry to story interview ui"
```

## Self-Review Checklist

- Spec coverage:
  - runtime projections are implemented in Task 1
  - projection-driven story prompt assembly and failure classification are implemented in Task 2
  - explicit retry, save-from-draft, delete/reset, and legacy mirrors are implemented in Task 3
  - explicit `Generate / Refine` vs. `Retry same input` UI behavior is implemented in Task 4
- Placeholder scan:
  - no red-flag placeholders or missing command details remain
- Type consistency:
  - the plan uses `draft_basis_attempt_id` consistently
  - `draft_projection.kind` uses `complete_draft` / `incomplete_draft`
  - `request_projection` always stores `request_snapshot_id`, `payload`, and provenance fields
