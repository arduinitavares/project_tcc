from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from services import story_runtime


def _base_state() -> Dict[str, Any]:
    return {
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
    }


def _valid_story_output(
    parent_requirement: str,
    *,
    is_complete: bool = True,
) -> str:
    return json.dumps(
        {
            "parent_requirement": parent_requirement,
            "user_stories": [
                {
                    "story_title": "Projection-backed story",
                    "statement": "As a developer, I want projection-aware drafts, so that retries stay deterministic.",
                    "acceptance_criteria": [
                        "Verify that reusable drafts come from projections."
                    ],
                    "invest_score": "High",
                    "estimated_effort": "S",
                    "produced_artifacts": [],
                }
            ],
            "is_complete": is_complete,
            "clarifying_questions": [],
        }
    )


@pytest.mark.asyncio
async def test_run_story_agent_from_state_uses_latest_reusable_projection_draft(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_invoke(payload):
        captured["payload"] = payload
        return _valid_story_output(payload.parent_requirement)

    monkeypatch.setattr(story_runtime, "_invoke_story_agent", fake_invoke)

    state = _base_state()
    state["story_attempts"] = {
        "Requirement A": [
            {
                "output_artifact": {
                    "parent_requirement": "Requirement A",
                    "user_stories": [
                        {
                            "story_title": "Wrong raw draft",
                            "statement": "As a team, I want the wrong draft, so that this test catches raw attempt lookups.",
                            "acceptance_criteria": ["Verify that raw attempt lookup is not used."],
                            "invest_score": "High",
                            "estimated_effort": "S",
                            "produced_artifacts": [],
                        }
                    ],
                    "is_complete": True,
                    "clarifying_questions": [],
                }
            }
        ]
    }
    state["interview_runtime"] = {
        "story": {
            "Requirement A": {
                "attempt_history": [
                    {
                        "attempt_id": "attempt-1",
                        "classification": "reusable_content_result",
                        "is_reusable": True,
                        "retryable": False,
                        "draft_kind": "complete_draft",
                        "output_artifact": {
                            "parent_requirement": "Requirement A",
                            "user_stories": [
                                {
                                    "story_title": "Projection draft",
                                    "statement": "As a developer, I want the projection draft, so that the runtime reuses the right attempt.",
                                    "acceptance_criteria": [
                                        "Verify that the projection draft is injected."
                                    ],
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
                "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                "request_projection": {},
            }
        }
    }

    result = await story_runtime.run_story_agent_from_state(
        state,
        project_id=1,
        parent_requirement="Requirement A",
        user_input=None,
    )

    assert result["success"] is True
    assert "--- PREVIOUS DRAFT TO REFINE ---" in captured["payload"].requirement_context
    assert "Projection draft" in captured["payload"].requirement_context
    assert "Wrong raw draft" not in captured["payload"].requirement_context


@pytest.mark.asyncio
async def test_run_story_agent_from_state_includes_only_unabsorbed_feedback(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_invoke(payload):
        captured["payload"] = payload
        return _valid_story_output(payload.parent_requirement)

    monkeypatch.setattr(story_runtime, "_invoke_story_agent", fake_invoke)

    state = _base_state()
    state["interview_runtime"] = {
        "story": {
            "Requirement A": {
                "attempt_history": [],
                "draft_projection": {},
                "feedback_projection": {
                    "items": [
                        {
                            "feedback_id": "feedback-1",
                            "text": "Please narrow the scope.",
                            "status": "unabsorbed",
                            "absorbed_by_attempt_id": None,
                        },
                        {
                            "feedback_id": "feedback-2",
                            "text": "This older feedback was already handled.",
                            "status": "absorbed",
                            "absorbed_by_attempt_id": "attempt-1",
                        },
                    ],
                    "next_feedback_sequence": 2,
                },
                "request_projection": {},
            }
        }
    }

    result = await story_runtime.run_story_agent_from_state(
        state,
        project_id=1,
        parent_requirement="Requirement A",
        user_input=None,
    )

    assert result["success"] is True
    assert "--- USER REFINEMENT FEEDBACK ---" in captured["payload"].requirement_context
    assert "Please narrow the scope." in captured["payload"].requirement_context
    assert "This older feedback was already handled." not in captured["payload"].requirement_context


@pytest.mark.asyncio
async def test_story_runtime_invalid_json_is_nonreusable_schema_failure(monkeypatch) -> None:
    async def fake_invoke(_payload):
        return '{"broken": '

    monkeypatch.setattr(story_runtime, "_invoke_story_agent", fake_invoke)

    result = await story_runtime.run_story_agent_from_state(
        _base_state(),
        project_id=1,
        parent_requirement="Requirement A",
        user_input=None,
    )

    assert result["success"] is False
    assert result["failure_stage"] == "invalid_json"
    assert result["classification"] == "nonreusable_schema_failure"
    assert result["is_reusable"] is False
    assert result["draft_kind"] is None


@pytest.mark.asyncio
async def test_story_runtime_replay_uses_frozen_request_payload(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    async def fake_invoke(payload):
        captured["payload"] = payload.model_dump()
        return _valid_story_output(payload.parent_requirement)

    monkeypatch.setattr(story_runtime, "_invoke_story_agent", fake_invoke)

    request_payload = {
        "parent_requirement": "Requirement A",
        "requirement_context": "Frozen request payload",
        "technical_spec": "SPEC",
        "compiled_authority": '{"ok": true}',
        "global_roadmap_context": "",
        "already_generated_milestone_stories": "",
        "artifact_registry": {},
    }

    result = await story_runtime.run_story_agent_request(
        request_payload,
        project_id=1,
        parent_requirement="Requirement A",
    )

    assert captured["payload"] == request_payload
    assert result["classification"] == "reusable_content_result"
    assert result["draft_kind"] == "complete_draft"
    assert result["request_payload"] == request_payload
