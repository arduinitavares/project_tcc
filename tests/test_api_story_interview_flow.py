from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient

import api as api_module


@dataclass
class DummyProduct:
    product_id: int
    name: str
    description: Optional[str] = None
    spec_file_path: Optional[str] = None
    compiled_authority_json: Optional[str] = None


class DummyProductRepository:
    def __init__(self) -> None:
        self.products = []

    def get_by_id(self, product_id: int):
        for product in self.products:
            if product.product_id == product_id:
                return product
        return None

    def create(self, name: str) -> DummyProduct:
        product = DummyProduct(
            product_id=len(self.products) + 1,
            name=name,
        )
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


def _story_artifact(parent_requirement: str, title: str, *, is_complete: bool = True) -> Dict[str, Any]:
    return {
        "parent_requirement": parent_requirement,
        "user_stories": [
            {
                "story_title": title,
                "statement": "As a developer, I want projection-aware drafts, so that retries and saves stay stable.",
                "acceptance_criteria": ["Verify the API reads the reusable projection."],
                "invest_score": "High",
                "estimated_effort": "S",
                "produced_artifacts": [],
            }
        ],
        "is_complete": is_complete,
        "clarifying_questions": [],
    }


def _build_client(monkeypatch):
    repo = DummyProductRepository()
    workflow = DummyWorkflowService()
    monkeypatch.setattr(api_module, "product_repo", repo)
    monkeypatch.setattr(api_module, "workflow_service", workflow)
    return TestClient(api_module.app), repo, workflow


def test_story_generate_promotes_reusable_draft_records_request_projection_and_absorbs_feedback(
    monkeypatch,
):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "roadmap_releases": [{"items": ["Requirement A"]}],
    }

    request_payload = {
        "parent_requirement": "Requirement A",
        "requirement_context": "assembled",
        "technical_spec": "SPEC",
        "compiled_authority": '{"ok": true}',
        "global_roadmap_context": "",
        "already_generated_milestone_stories": "",
        "artifact_registry": {},
    }

    async def fake_run_story_agent_from_state(
        state,
        *,
        project_id,
        parent_requirement,
        user_input,
    ):
        assert project_id == product.product_id
        assert parent_requirement == "Requirement A"
        assert user_input == "Please keep this to one milestone."
        assert state["roadmap_releases"][0]["items"] == ["Requirement A"]
        return {
            "success": True,
            "input_context": {"requirement_context": "assembled"},
            "output_artifact": _story_artifact(parent_requirement, "Story A"),
            "classification": "reusable_content_result",
            "draft_kind": "complete_draft",
            "is_reusable": True,
            "is_complete": True,
            "request_payload": request_payload,
            "error": None,
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
    assert payload["output_artifact"]["user_stories"][0]["story_title"] == "Story A"
    assert payload["current_draft"] == {
        "attempt_id": "attempt-1",
        "kind": "complete_draft",
        "is_complete": True,
    }
    assert payload["retry"] == {
        "available": False,
        "target_attempt_id": None,
    }
    assert payload["save"] == {"available": True}

    state = workflow.states[str(product.product_id)]
    runtime = state["interview_runtime"]["story"]["Requirement A"]
    assert runtime["request_projection"]["payload"] == request_payload
    assert runtime["request_projection"]["included_feedback_ids"] == ["feedback-1"]
    assert runtime["draft_projection"] == {
        "latest_reusable_attempt_id": "attempt-1",
        "kind": "complete_draft",
        "is_complete": True,
        "updated_at": runtime["draft_projection"]["updated_at"],
    }
    assert runtime["attempt_history"][0]["included_feedback_ids"] == ["feedback-1"]
    assert runtime["attempt_history"][0]["classification"] == "reusable_content_result"
    assert runtime["feedback_projection"]["items"] == [
        {
            "feedback_id": "feedback-1",
            "text": "Please keep this to one milestone.",
            "created_at": runtime["feedback_projection"]["items"][0]["created_at"],
            "status": "absorbed",
            "absorbed_by_attempt_id": "attempt-1",
        }
    ]
    assert state["story_outputs"]["Requirement A"]["user_stories"][0]["story_title"] == "Story A"
    assert len(state["story_attempts"]["Requirement A"]) == 1


def test_story_retry_replays_frozen_request_and_preserves_prior_good_draft_when_retry_fails(
    monkeypatch,
):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    reusable_artifact = _story_artifact("Requirement A", "Saved draft")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "roadmap_releases": [{"items": ["Requirement A"]}],
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "created_at": "2026-03-28T10:00:00Z",
                            "trigger": "manual_refine",
                            "request_snapshot_id": "request-1",
                            "draft_basis_attempt_id": None,
                            "included_feedback_ids": [],
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": reusable_artifact,
                            "failure_artifact_id": None,
                            "failure_stage": None,
                            "failure_summary": None,
                            "raw_output_preview": None,
                            "has_full_artifact": False,
                        },
                        {
                            "attempt_id": "attempt-2",
                            "created_at": "2026-03-28T10:05:00Z",
                            "trigger": "manual_refine",
                            "request_snapshot_id": "request-2",
                            "draft_basis_attempt_id": "attempt-1",
                            "included_feedback_ids": [],
                            "classification": "nonreusable_provider_failure",
                            "is_reusable": False,
                            "retryable": True,
                            "draft_kind": None,
                            "output_artifact": {
                                "error": "STORY_GENERATION_FAILED",
                                "message": "provider timeout",
                            },
                            "failure_artifact_id": "story-failure-1",
                            "failure_stage": "invocation_exception",
                            "failure_summary": "provider timeout",
                            "raw_output_preview": None,
                            "has_full_artifact": True,
                        },
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                        "updated_at": "2026-03-28T10:00:00Z",
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
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
                        "request_hash": "hash-2",
                        "created_at": "2026-03-28T10:05:00Z",
                        "draft_basis_attempt_id": "attempt-1",
                        "included_feedback_ids": [],
                        "context_version": "story-runtime.v1",
                    },
                }
            }
        },
    }

    async def fake_retry(request_payload, *, project_id, parent_requirement):
        assert request_payload["requirement_context"] == "frozen"
        assert project_id == product.product_id
        assert parent_requirement == "Requirement A"
        return {
            "success": False,
            "input_context": request_payload,
            "output_artifact": {
                "error": "STORY_GENERATION_FAILED",
                "message": "provider timeout again",
            },
            "classification": "nonreusable_provider_failure",
            "draft_kind": None,
            "is_reusable": False,
            "is_complete": None,
            "request_payload": request_payload,
            "error": "provider timeout again",
            "failure_artifact_id": "story-failure-2",
            "failure_stage": "invocation_exception",
            "failure_summary": "provider timeout again",
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
    assert payload["retry"] == {
        "available": True,
        "target_attempt_id": "attempt-3",
    }
    assert payload["save"] == {"available": True}
    assert payload["current_draft"] == {
        "attempt_id": "attempt-1",
        "kind": "complete_draft",
        "is_complete": True,
    }

    runtime = workflow.states[str(product.product_id)]["interview_runtime"]["story"]["Requirement A"]
    assert runtime["draft_projection"]["latest_reusable_attempt_id"] == "attempt-1"
    assert runtime["attempt_history"][-1]["attempt_id"] == "attempt-3"
    assert runtime["attempt_history"][-1]["trigger"] == "retry_same_input"
    assert runtime["attempt_history"][-1]["request_snapshot_id"] == "request-2"


def test_story_retry_promotes_reusable_draft_and_absorbs_frozen_feedback_ids(
    monkeypatch,
):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    prior_artifact = _story_artifact("Requirement A", "Earlier draft", is_complete=False)
    retry_artifact = _story_artifact("Requirement A", "Recovered draft")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "created_at": "2026-03-28T10:00:00Z",
                            "trigger": "auto_transition",
                            "request_snapshot_id": "request-1",
                            "draft_basis_attempt_id": None,
                            "included_feedback_ids": [],
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "incomplete_draft",
                            "output_artifact": prior_artifact,
                            "failure_artifact_id": None,
                            "failure_stage": None,
                            "failure_summary": None,
                            "raw_output_preview": None,
                            "has_full_artifact": False,
                        },
                        {
                            "attempt_id": "attempt-2",
                            "created_at": "2026-03-28T10:05:00Z",
                            "trigger": "manual_refine",
                            "request_snapshot_id": "request-2",
                            "draft_basis_attempt_id": "attempt-1",
                            "included_feedback_ids": ["feedback-1"],
                            "classification": "nonreusable_provider_failure",
                            "is_reusable": False,
                            "retryable": True,
                            "draft_kind": None,
                            "output_artifact": {
                                "error": "STORY_GENERATION_FAILED",
                                "message": "provider timeout",
                            },
                            "failure_artifact_id": "story-failure-1",
                            "failure_stage": "invocation_exception",
                            "failure_summary": "provider timeout",
                            "raw_output_preview": None,
                            "has_full_artifact": True,
                        },
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "incomplete_draft",
                        "is_complete": False,
                        "updated_at": "2026-03-28T10:00:00Z",
                    },
                    "feedback_projection": {
                        "items": [
                            {
                                "feedback_id": "feedback-1",
                                "text": "Please make the draft complete.",
                                "created_at": "2026-03-28T10:04:00Z",
                                "status": "unabsorbed",
                                "absorbed_by_attempt_id": None,
                            }
                        ],
                        "next_feedback_sequence": 1,
                    },
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
                        "request_hash": "hash-2",
                        "created_at": "2026-03-28T10:05:00Z",
                        "draft_basis_attempt_id": "attempt-1",
                        "included_feedback_ids": ["feedback-1"],
                        "context_version": "story-runtime.v1",
                    },
                }
            }
        },
    }

    async def fake_retry(request_payload, *, project_id, parent_requirement):
        assert request_payload["requirement_context"] == "frozen"
        assert project_id == product.product_id
        assert parent_requirement == "Requirement A"
        return {
            "success": True,
            "input_context": request_payload,
            "output_artifact": retry_artifact,
            "classification": "reusable_content_result",
            "draft_kind": "complete_draft",
            "is_reusable": True,
            "is_complete": True,
            "request_payload": request_payload,
            "error": None,
            "failure_artifact_id": None,
            "failure_stage": None,
            "failure_summary": None,
            "raw_output_preview": None,
            "has_full_artifact": False,
        }

    monkeypatch.setattr(api_module, "run_story_agent_request", fake_retry)

    response = client.post(
        f"/api/projects/{product.product_id}/story/retry",
        params={"parent_requirement": "Requirement A"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["current_draft"] == {
        "attempt_id": "attempt-3",
        "kind": "complete_draft",
        "is_complete": True,
    }
    assert payload["retry"] == {
        "available": False,
        "target_attempt_id": None,
    }
    assert payload["save"] == {"available": True}

    runtime = workflow.states[str(product.product_id)]["interview_runtime"]["story"]["Requirement A"]
    assert runtime["draft_projection"] == {
        "latest_reusable_attempt_id": "attempt-3",
        "kind": "complete_draft",
        "is_complete": True,
        "updated_at": runtime["draft_projection"]["updated_at"],
    }
    assert runtime["attempt_history"][-1]["attempt_id"] == "attempt-3"
    assert runtime["attempt_history"][-1]["included_feedback_ids"] == ["feedback-1"]
    assert runtime["feedback_projection"]["items"] == [
        {
            "feedback_id": "feedback-1",
            "text": "Please make the draft complete.",
            "created_at": "2026-03-28T10:04:00Z",
            "status": "absorbed",
            "absorbed_by_attempt_id": "attempt-3",
        }
    ]
    assert (
        workflow.states[str(product.product_id)]["story_outputs"]["Requirement A"]["user_stories"][0]["story_title"]
        == "Recovered draft"
    )


def test_story_retry_rejects_when_latest_attempt_is_not_retryable_even_with_frozen_payload(
    monkeypatch,
):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "created_at": "2026-03-28T10:00:00Z",
                            "trigger": "auto_transition",
                            "request_snapshot_id": "request-1",
                            "draft_basis_attempt_id": None,
                            "included_feedback_ids": [],
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": _story_artifact("Requirement A", "Saved draft"),
                            "failure_artifact_id": None,
                            "failure_stage": None,
                            "failure_summary": None,
                            "raw_output_preview": None,
                            "has_full_artifact": False,
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                        "updated_at": "2026-03-28T10:00:00Z",
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {
                        "request_snapshot_id": "request-1",
                        "payload": {
                            "parent_requirement": "Requirement A",
                            "requirement_context": "frozen",
                            "technical_spec": "SPEC",
                            "compiled_authority": '{"ok": true}',
                            "global_roadmap_context": "",
                            "already_generated_milestone_stories": "",
                            "artifact_registry": {},
                        },
                        "request_hash": "hash-1",
                        "created_at": "2026-03-28T10:00:00Z",
                        "draft_basis_attempt_id": None,
                        "included_feedback_ids": [],
                        "context_version": "story-runtime.v1",
                    },
                }
            }
        },
    }

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("retry should be rejected before invoking the story runtime")

    monkeypatch.setattr(api_module, "run_story_agent_request", fail_if_called)

    response = client.post(
        f"/api/projects/{product.product_id}/story/retry",
        params={"parent_requirement": "Requirement A"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "The latest story attempt is not eligible for retry."


def test_story_save_uses_complete_reusable_draft_projection_not_latest_failed_attempt(
    monkeypatch,
):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    reusable_artifact = _story_artifact("Requirement A", "Saved draft")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": reusable_artifact,
                        },
                        {
                            "attempt_id": "attempt-2",
                            "classification": "nonreusable_provider_failure",
                            "is_reusable": False,
                            "retryable": True,
                            "draft_kind": None,
                            "output_artifact": {
                                "error": "STORY_GENERATION_FAILED",
                                "message": "provider timeout",
                                "is_complete": False,
                            },
                        },
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {},
                }
            }
        },
    }

    async def fake_hydrate_context(session_id: str, project_id: int) -> SimpleNamespace:
        assert session_id == str(product.product_id)
        assert project_id == product.product_id
        return SimpleNamespace(
            state=workflow.states[str(product.product_id)],
            session_id=session_id,
        )

    def fake_save_stories_tool(save_input, _context):
        assert save_input.parent_requirement == "Requirement A"
        assert save_input.stories == reusable_artifact["user_stories"]
        return {"success": True, "saved_count": 1}

    monkeypatch.setattr(api_module, "_hydrate_context", fake_hydrate_context)
    monkeypatch.setattr(api_module, "save_stories_tool", fake_save_stories_tool)

    response = client.post(
        f"/api/projects/{product.product_id}/story/save",
        params={"parent_requirement": "Requirement A"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert workflow.states[str(product.product_id)]["story_saved"]["Requirement A"] is True


def test_story_save_returns_409_without_complete_reusable_draft_projection(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [],
                    "draft_projection": {},
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {},
                }
            }
        },
    }

    response = client.post(
        f"/api/projects/{product.product_id}/story/save",
        params={"parent_requirement": "Requirement A"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "No story draft available for 'Requirement A'"


def test_story_history_returns_projection_attempt_history_and_summary(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": _story_artifact("Requirement A", "Saved draft"),
                        },
                        {
                            "attempt_id": "attempt-2",
                            "classification": "nonreusable_provider_failure",
                            "is_reusable": False,
                            "retryable": True,
                            "draft_kind": None,
                            "output_artifact": {
                                "error": "STORY_GENERATION_FAILED",
                                "message": "provider timeout",
                            },
                        },
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {
                        "request_snapshot_id": "request-2",
                        "payload": {
                            "parent_requirement": "Requirement A",
                        },
                    },
                }
            }
        },
    }

    response = client.get(
        f"/api/projects/{product.product_id}/story/history",
        params={"parent_requirement": "Requirement A"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["count"] == 2
    assert payload["items"][0]["attempt_id"] == "attempt-1"
    assert payload["items"][1]["attempt_id"] == "attempt-2"
    assert payload["current_draft"] == {
        "attempt_id": "attempt-1",
        "kind": "complete_draft",
        "is_complete": True,
    }
    assert payload["retry"] == {
        "available": True,
        "target_attempt_id": "attempt-2",
    }
    assert payload["save"] == {"available": True}


def test_story_generate_allows_fresh_run_after_reset_without_manual_refinement_input(
    monkeypatch,
):
    client, repo, workflow = _build_client(monkeypatch)
    product = repo.create("Story Project")
    request_payload = {
        "parent_requirement": "Requirement A",
        "requirement_context": "reset fresh start",
        "technical_spec": "SPEC",
        "compiled_authority": '{"ok": true}',
        "global_roadmap_context": "",
        "already_generated_milestone_stories": "",
        "artifact_registry": {},
    }
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_INTERVIEW",
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "roadmap_releases": [{"items": ["Requirement A"]}],
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "created_at": "2026-03-28T10:00:00Z",
                            "trigger": "manual_refine",
                            "request_snapshot_id": "request-1",
                            "draft_basis_attempt_id": None,
                            "included_feedback_ids": [],
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": _story_artifact("Requirement A", "Old draft"),
                            "failure_artifact_id": None,
                            "failure_stage": None,
                            "failure_summary": None,
                            "raw_output_preview": None,
                            "has_full_artifact": False,
                        },
                        {
                            "attempt_id": "reset-marker-2",
                            "created_at": "2026-03-28T10:05:00Z",
                            "trigger": "reset",
                            "classification": "reset_marker",
                            "is_reusable": False,
                            "retryable": False,
                            "summary": "Stories deleted and state reset by user.",
                            "output_artifact": None,
                        },
                    ],
                    "draft_projection": {},
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {},
                }
            }
        },
    }

    async def fake_run_story_agent_from_state(
        state,
        *,
        project_id,
        parent_requirement,
        user_input,
    ):
        assert project_id == product.product_id
        assert parent_requirement == "Requirement A"
        assert user_input is None
        return {
            "success": True,
            "input_context": {"requirement_context": "reset fresh start"},
            "output_artifact": _story_artifact(parent_requirement, "New draft"),
            "classification": "reusable_content_result",
            "draft_kind": "complete_draft",
            "is_reusable": True,
            "is_complete": True,
            "request_payload": request_payload,
            "error": None,
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
        json={},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["current_draft"] == {
        "attempt_id": "attempt-3",
        "kind": "complete_draft",
        "is_complete": True,
    }
    runtime = workflow.states[str(product.product_id)]["interview_runtime"]["story"]["Requirement A"]
    assert runtime["attempt_history"][-1]["attempt_id"] == "attempt-3"
    assert runtime["attempt_history"][-1]["trigger"] == "auto_transition"
    assert runtime["request_projection"]["included_feedback_ids"] == []
