from types import SimpleNamespace

import pytest

from services.phases.story_service import (
    StoryPhaseError,
    complete_story_phase,
    delete_story_requirement,
    generate_story_draft,
    get_story_history,
    get_story_pending,
    merge_story_resolution,
    retry_story_draft,
    save_story_draft,
)


def _story_artifact(parent_requirement: str, title: str, *, is_complete: bool = True):
    return {
        "parent_requirement": parent_requirement,
        "user_stories": [
            {
                "story_title": title,
                "statement": "As a developer, I want projection-aware drafts, so that retries and saves stay stable.",
                "acceptance_criteria": [
                    "Verify the service reads the reusable projection."
                ],
                "invest_score": "High",
                "estimated_effort": "S",
                "produced_artifacts": [],
            }
        ],
        "is_complete": is_complete,
        "clarifying_questions": [],
    }


def _merge_recommended_artifact(parent_requirement: str):
    artifact = _story_artifact(
        parent_requirement,
        "Validate execution evidence meets submission standards",
        is_complete=False,
    )
    artifact["user_stories"][0]["invest_score"] = "Low"
    artifact["user_stories"][0]["acceptance_criteria"] = [
        "Move the validation checklist into the owning requirement.",
    ]
    artifact["user_stories"][0]["decomposition_warning"] = (
        "Artifact 'application_execution_evidence' is owned by "
        "'Updated Source Code Package (refactored prototype for submission)' "
        "which already has a creation story. Recommend consolidating: merge this "
        "validation into the evidence creation story and retire this separate requirement."
    )
    return artifact


def _pending_state():
    return {
        "roadmap_releases": [
            {
                "theme": "Milestone 1",
                "reasoning": "First slice",
                "items": [
                    "Requirement A",
                    "Requirement B",
                ],
            }
        ],
        "story_saved": {"Requirement A": True},
        "story_attempts": {
            "Requirement A": [
                {
                    "created_at": "2026-03-28T10:00:00Z",
                    "trigger": "manual_refine",
                    "input_context": {},
                    "output_artifact": _story_artifact("Requirement A", "Saved draft"),
                    "is_complete": True,
                    "failure_artifact_id": None,
                    "failure_stage": None,
                    "failure_summary": None,
                    "raw_output_preview": None,
                    "has_full_artifact": False,
                }
            ],
            "Requirement B": [
                {
                    "created_at": "2026-03-28T10:00:00Z",
                    "trigger": "manual_refine",
                    "input_context": {},
                    "output_artifact": {},
                    "is_complete": False,
                    "failure_artifact_id": None,
                    "failure_stage": None,
                    "failure_summary": None,
                    "raw_output_preview": None,
                    "has_full_artifact": False,
                }
            ],
        },
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "trigger": "manual_refine",
                            "input_context": {},
                            "output_artifact": _story_artifact(
                                "Requirement A",
                                "Saved draft",
                            ),
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {},
                },
                "Requirement B": {
                    "phase": "story",
                    "subject_key": "Requirement B",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "trigger": "manual_refine",
                            "input_context": {},
                            "output_artifact": {},
                            "classification": "nonreusable_provider_failure",
                            "is_reusable": False,
                            "retryable": True,
                            "draft_kind": None,
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": None,
                        "kind": "incomplete_draft",
                        "is_complete": False,
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {},
                },
            }
        },
    }


@pytest.mark.asyncio
async def test_get_story_history_returns_attempts_and_projection_summary():
    state = {
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
                            "output_artifact": _story_artifact(
                                "Requirement A", "Saved draft"
                            ),
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
                        "payload": {"parent_requirement": "Requirement A"},
                    },
                }
            }
        }
    }

    payload = await get_story_history(
        parent_requirement="  Requirement A  ",
        load_state=lambda: _async_value(state),
    )

    assert payload["parent_requirement"] == "Requirement A"
    data = payload["data"]
    assert data["count"] == 2
    assert data["items"][0]["attempt_id"] == "attempt-1"
    assert data["current_draft"] == {
        "attempt_id": "attempt-1",
        "kind": "complete_draft",
        "is_complete": True,
    }
    assert data["retry"] == {
        "available": True,
        "target_attempt_id": "attempt-2",
    }
    assert data["save"] == {"available": True}


@pytest.mark.asyncio
async def test_get_story_pending_groups_requirements_by_status():
    state = _pending_state()

    payload = await get_story_pending(load_state=lambda: _async_value(state))

    assert payload["total_count"] == 2
    assert payload["saved_count"] == 1
    assert payload["grouped_items"] == [
        {
            "group_id": "milestone_0",
            "theme": "Milestone 1",
            "reasoning": "First slice",
            "requirements": [
                {
                    "requirement": "Requirement A",
                    "status": "Saved",
                    "attempt_count": 1,
                },
                {
                    "requirement": "Requirement B",
                    "status": "Attempted",
                    "attempt_count": 1,
                },
            ],
        }
    ]


@pytest.mark.asyncio
async def test_generate_story_draft_normalizes_requirement_and_persists_reusable_output():
    state = {
        "roadmap_releases": [
            {
                "items": ["Requirement A"],
            }
        ],
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [],
                    "draft_projection": {},
                    "feedback_projection": {
                        "items": [
                            {
                                "feedback_id": "feedback-1",
                                "text": "Please keep this to one milestone.",
                                "created_at": "2026-03-28T09:59:00Z",
                                "status": "unabsorbed",
                                "absorbed_by_attempt_id": None,
                            }
                        ],
                        "next_feedback_sequence": 1,
                    },
                    "request_projection": {},
                }
            }
        },
    }
    saved_states: list[dict[str, object]] = []
    captured: dict[str, object] = {}

    async def fake_run_story_agent_from_state(
        state_arg,
        *,
        project_id,
        parent_requirement,
        user_input,
    ):
        assert project_id == 7
        assert parent_requirement == "Requirement A"
        assert user_input is None
        captured["feedback"] = state_arg["interview_runtime"]["story"]["Requirement A"][
            "feedback_projection"
        ]["items"]
        return {
            "success": True,
            "input_context": {"requirement_context": "assembled"},
            "output_artifact": _story_artifact("Requirement A", "Story A"),
            "classification": "reusable_content_result",
            "draft_kind": "complete_draft",
            "is_reusable": True,
            "is_complete": True,
            "request_payload": {"parent_requirement": "Requirement A"},
            "error": None,
            "failure_artifact_id": None,
            "failure_stage": None,
            "failure_summary": None,
            "raw_output_preview": None,
            "has_full_artifact": False,
        }

    payload = await generate_story_draft(
        project_id=7,
        parent_requirement="  Requirement A  ",
        user_input="Please keep this to one milestone.",
        load_state=lambda: _async_value(state),
        save_state=lambda updated: saved_states.append(dict(updated)),
        now_iso=lambda: "2026-04-04T12:00:00Z",
        run_story_agent_from_state=fake_run_story_agent_from_state,
        append_feedback_entry=lambda runtime, text, created_at: runtime[
            "feedback_projection"
        ]["items"].append(
            {
                "feedback_id": f"feedback-{len(runtime['feedback_projection']['items']) + 1}",
                "text": text,
                "created_at": created_at,
                "status": "unabsorbed",
                "absorbed_by_attempt_id": None,
            }
        ),
        set_request_projection=lambda runtime, **kwargs: (
            runtime.setdefault("request_projection", {}).update(kwargs)
            or runtime["request_projection"]
        ),
        append_attempt=lambda runtime, attempt: runtime.setdefault(
            "attempt_history", []
        ).append(attempt),
        promote_reusable_draft=lambda runtime, **kwargs: runtime.setdefault(
            "draft_projection", {}
        ).update(
            {
                "latest_reusable_attempt_id": kwargs["attempt_id"],
                "kind": kwargs["kind"],
                "is_complete": kwargs["is_complete"],
                "updated_at": kwargs["updated_at"],
            }
        ),
        mark_feedback_absorbed=lambda runtime, *, feedback_ids, attempt_id: [
            item.update({"status": "absorbed", "absorbed_by_attempt_id": attempt_id})
            for item in runtime["feedback_projection"]["items"]
            if item["feedback_id"] in set(feedback_ids)
        ],
        failure_meta=lambda story_result, fallback_summary: {},
    )

    assert payload["parent_requirement"] == "Requirement A"
    assert (
        payload["data"]["output_artifact"]["user_stories"][0]["story_title"]
        == "Story A"
    )
    assert payload["data"]["current_draft"] == {
        "attempt_id": "attempt-1",
        "kind": "complete_draft",
        "is_complete": True,
    }
    assert captured["feedback"][0]["status"] == "absorbed"
    assert state["interview_runtime"]["story"]["Requirement A"]["request_projection"][
        "payload"
    ] == {"parent_requirement": "Requirement A"}
    assert (
        state["story_outputs"]["Requirement A"]["user_stories"][0]["story_title"]
        == "Story A"
    )
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_retry_story_draft_replays_request_projection_and_promotes_reusable_output():
    state = {
        "interview_runtime": {
            "story": {
                "Requirement A": {
                    "phase": "story",
                    "subject_key": "Requirement A",
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "trigger": "manual_refine",
                            "input_context": {},
                            "output_artifact": _story_artifact(
                                "Requirement A", "Saved draft"
                            ),
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                        },
                        {
                            "attempt_id": "attempt-2",
                            "trigger": "manual_refine",
                            "input_context": {},
                            "output_artifact": {
                                "error": "STORY_GENERATION_FAILED",
                                "message": "provider timeout",
                            },
                            "classification": "nonreusable_provider_failure",
                            "is_reusable": False,
                            "retryable": True,
                            "draft_kind": None,
                        },
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {
                        "request_snapshot_id": "request-1",
                        "payload": {"parent_requirement": "Requirement A"},
                        "included_feedback_ids": ["feedback-1"],
                        "draft_basis_attempt_id": "attempt-1",
                    },
                }
            }
        }
    }
    saved_states: list[dict[str, object]] = []

    async def fake_run_story_agent_request(
        request_payload, *, project_id, parent_requirement
    ):
        assert project_id == 7
        assert parent_requirement == "Requirement A"
        assert request_payload == {"parent_requirement": "Requirement A"}
        return {
            "success": True,
            "input_context": {"request": "replayed"},
            "output_artifact": _story_artifact("Requirement A", "Retried story"),
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

    payload = await retry_story_draft(
        project_id=7,
        parent_requirement="  Requirement A  ",
        load_state=lambda: _async_value(state),
        save_state=lambda updated: saved_states.append(dict(updated)),
        now_iso=lambda: "2026-04-04T12:00:00Z",
        run_story_agent_request=fake_run_story_agent_request,
        append_attempt=lambda runtime, attempt: runtime.setdefault(
            "attempt_history", []
        ).append(attempt),
        promote_reusable_draft=lambda runtime, **kwargs: runtime.setdefault(
            "draft_projection", {}
        ).update(
            {
                "latest_reusable_attempt_id": kwargs["attempt_id"],
                "kind": kwargs["kind"],
                "is_complete": kwargs["is_complete"],
                "updated_at": kwargs["updated_at"],
            }
        ),
        mark_feedback_absorbed=lambda runtime, *, feedback_ids, attempt_id: None,
        failure_meta=lambda story_result, fallback_summary: {},
    )

    assert payload["parent_requirement"] == "Requirement A"
    assert (
        payload["data"]["output_artifact"]["user_stories"][0]["story_title"]
        == "Retried story"
    )
    assert payload["data"]["retry"] == {
        "available": False,
        "target_attempt_id": None,
    }
    assert (
        state["story_outputs"]["Requirement A"]["user_stories"][0]["story_title"]
        == "Retried story"
    )
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_save_story_draft_marks_requirement_saved_and_persists_state():
    artifact = _story_artifact("Requirement A", "Saved draft")
    state = {
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
                            "output_artifact": artifact,
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
    }
    hydrated = SimpleNamespace(state=state, session_id="7")
    saved_states: list[dict[str, object]] = []
    captured: dict[str, object] = {}

    def save_state(updated: dict[str, object]) -> None:
        saved_states.append(dict(updated))

    async def hydrate_context(session_id: str, project_id: int):
        assert session_id == "7"
        assert project_id == 7
        return hydrated

    def fake_save_stories_tool(save_input, _context):
        captured["stories"] = save_input.stories
        return {"success": True, "saved_count": 1}

    payload = await save_story_draft(
        project_id=7,
        parent_requirement="  Requirement A  ",
        load_state=lambda: _async_value(state),
        save_state=save_state,
        hydrate_context=hydrate_context,
        build_tool_context=lambda context: context,
        save_stories_tool=fake_save_stories_tool,
    )

    assert payload["parent_requirement"] == "Requirement A"
    assert payload["data"]["save_result"]["saved_count"] == 1
    assert state["story_saved"]["Requirement A"] is True
    assert (
        state["story_outputs"]["Requirement A"]["user_stories"][0]["story_title"]
        == "Saved draft"
    )
    assert captured["stories"] == artifact["user_stories"]
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_merge_story_resolution_normalizes_requirement_name():
    merge_artifact = _merge_recommended_artifact("Requirement A")
    state = {
        "roadmap_releases": [{"items": ["Requirement A"]}],
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
                            "draft_kind": "incomplete_draft",
                            "output_artifact": merge_artifact,
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "incomplete_draft",
                        "is_complete": False,
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {},
                }
            }
        },
    }
    saved_states: list[dict[str, object]] = []

    payload = await merge_story_resolution(
        parent_requirement="  Requirement A  ",
        load_state=lambda: _async_value(state),
        save_state=lambda updated: saved_states.append(dict(updated)),
        now_iso=lambda: "2026-04-04T12:00:00Z",
    )

    assert payload["parent_requirement"] == "Requirement A"
    resolution = payload["data"]["resolution"]["current"]
    assert (
        resolution["owner_requirement"]
        == "Updated Source Code Package (refactored prototype for submission)"
    )
    assert (
        state["interview_runtime"]["story"]["Requirement A"]["resolution_projection"]
        == resolution
    )
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_delete_story_requirement_normalizes_requirement_name():
    parent_requirement = "Requirement A"
    state = {
        "story_saved": {parent_requirement: True},
        "story_outputs": {parent_requirement: {"data": "some artifact"}},
        "story_attempts": {
            parent_requirement: [
                {
                    "created_at": "2026-03-28T10:00:00Z",
                    "trigger": "manual_refine",
                    "input_context": {},
                    "output_artifact": {"data": "some artifact"},
                    "is_complete": True,
                    "failure_artifact_id": None,
                    "failure_stage": None,
                    "failure_summary": None,
                    "raw_output_preview": None,
                    "has_full_artifact": False,
                }
            ]
        },
        "interview_runtime": {
            "story": {
                parent_requirement: {
                    "phase": "story",
                    "subject_key": parent_requirement,
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "created_at": "2026-03-28T10:00:00Z",
                            "trigger": "manual_refine",
                            "request_snapshot_id": "request-1",
                            "draft_basis_attempt_id": None,
                            "included_feedback_ids": ["feedback-1"],
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": {
                                "data": "some artifact",
                                "is_complete": True,
                            },
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
                    "feedback_projection": {
                        "items": [
                            {
                                "feedback_id": "feedback-1",
                                "text": "keep it smaller",
                                "created_at": "2026-03-28T09:59:00Z",
                                "status": "absorbed",
                                "absorbed_by_attempt_id": "attempt-1",
                            }
                        ],
                        "next_feedback_sequence": 1,
                    },
                    "request_projection": {
                        "request_snapshot_id": "request-1",
                        "payload": {"parent_requirement": parent_requirement},
                        "request_hash": "hash-1",
                        "created_at": "2026-03-28T10:00:00Z",
                        "draft_basis_attempt_id": None,
                        "included_feedback_ids": ["feedback-1"],
                        "context_version": "story-runtime.v1",
                    },
                }
            }
        },
        "another_req": "should not be touched",
    }
    saved_states: list[dict[str, object]] = []

    payload = await delete_story_requirement(
        parent_requirement="  Requirement A  ",
        load_state=lambda: _async_value(state),
        save_state=lambda updated: saved_states.append(dict(updated)),
        now_iso=lambda: "2026-04-04T12:00:00Z",
        delete_requirement_stories=lambda normalized_requirement: 3,
        reset_subject_working_set=_reset_subject_working_set,
    )

    assert payload["parent_requirement"] == "Requirement A"
    assert payload["data"] == {
        "deleted_count": 3,
        "message": "Stories deleted successfully",
    }
    assert parent_requirement not in state["story_saved"]
    assert parent_requirement not in state["story_outputs"]
    assert len(state["story_attempts"][parent_requirement]) == 1
    assert state["another_req"] == "should not be touched"
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_merge_story_resolution_persists_merged_projection():
    merge_artifact = _merge_recommended_artifact("Requirement A")
    state = {
        "roadmap_releases": [{"items": ["Requirement A"]}],
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
                            "draft_kind": "incomplete_draft",
                            "output_artifact": merge_artifact,
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "incomplete_draft",
                        "is_complete": False,
                    },
                    "feedback_projection": {"items": [], "next_feedback_sequence": 0},
                    "request_projection": {},
                }
            }
        },
    }
    saved_states: list[dict[str, object]] = []

    payload = await merge_story_resolution(
        parent_requirement="Requirement A",
        load_state=lambda: _async_value(state),
        save_state=lambda updated: saved_states.append(dict(updated)),
        now_iso=lambda: "2026-04-04T12:00:00Z",
    )

    assert payload["parent_requirement"] == "Requirement A"
    resolution = payload["data"]["resolution"]["current"]
    assert resolution["status"] == "merged"
    assert (
        resolution["owner_requirement"]
        == "Updated Source Code Package (refactored prototype for submission)"
    )
    assert resolution["resolved_at"] == "2026-04-04T12:00:00Z"
    assert (
        state["interview_runtime"]["story"]["Requirement A"]["resolution_projection"]
        == resolution
    )
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_complete_story_phase_moves_to_sprint_setup_once_story_is_saved():
    state = {
        "fsm_state": "STORY_PERSISTENCE",
        "roadmap_releases": [{"items": ["Enable login"]}],
        "story_saved": {"Enable login": True},
    }
    saved_states: list[dict[str, object]] = []

    payload = await complete_story_phase(
        load_state=lambda: _async_value(state),
        save_state=lambda updated: saved_states.append(dict(updated)),
        now_iso=lambda: "2026-04-04T12:00:00Z",
    )

    assert payload["fsm_state"] == "SPRINT_SETUP"
    assert state["fsm_state"] == "SPRINT_SETUP"
    assert state["story_phase_completed_at"] == "2026-04-04T12:00:00Z"
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_complete_story_phase_rejects_when_nothing_is_saved():
    state = {
        "fsm_state": "STORY_PERSISTENCE",
        "roadmap_releases": [{"items": ["Enable login"]}],
        "story_saved": {},
    }

    with pytest.raises(StoryPhaseError) as exc_info:
        await complete_story_phase(
            load_state=lambda: _async_value(state),
            save_state=lambda updated: None,
            now_iso=lambda: "2026-04-04T12:00:00Z",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "Cannot complete phase. No requirements have saved stories."
    )


@pytest.mark.asyncio
async def test_delete_story_requirement_resets_runtime_and_clears_saved_projection():
    parent_requirement = "Requirement A"
    state = {
        "story_saved": {parent_requirement: True},
        "story_outputs": {parent_requirement: {"data": "some artifact"}},
        "story_attempts": {
            parent_requirement: [
                {
                    "created_at": "2026-03-28T10:00:00Z",
                    "trigger": "manual_refine",
                    "input_context": {},
                    "output_artifact": {"data": "some artifact"},
                    "is_complete": True,
                    "failure_artifact_id": None,
                    "failure_stage": None,
                    "failure_summary": None,
                    "raw_output_preview": None,
                    "has_full_artifact": False,
                }
            ]
        },
        "interview_runtime": {
            "story": {
                parent_requirement: {
                    "phase": "story",
                    "subject_key": parent_requirement,
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "created_at": "2026-03-28T10:00:00Z",
                            "trigger": "manual_refine",
                            "request_snapshot_id": "request-1",
                            "draft_basis_attempt_id": None,
                            "included_feedback_ids": ["feedback-1"],
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": {
                                "data": "some artifact",
                                "is_complete": True,
                            },
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
                    "feedback_projection": {
                        "items": [
                            {
                                "feedback_id": "feedback-1",
                                "text": "keep it smaller",
                                "created_at": "2026-03-28T09:59:00Z",
                                "status": "absorbed",
                                "absorbed_by_attempt_id": "attempt-1",
                            }
                        ],
                        "next_feedback_sequence": 1,
                    },
                    "request_projection": {
                        "request_snapshot_id": "request-1",
                        "payload": {"parent_requirement": parent_requirement},
                        "request_hash": "hash-1",
                        "created_at": "2026-03-28T10:00:00Z",
                        "draft_basis_attempt_id": None,
                        "included_feedback_ids": ["feedback-1"],
                        "context_version": "story-runtime.v1",
                    },
                }
            }
        },
        "another_req": "should not be touched",
    }
    saved_states: list[dict[str, object]] = []

    payload = await delete_story_requirement(
        parent_requirement=parent_requirement,
        load_state=lambda: _async_value(state),
        save_state=lambda updated: saved_states.append(dict(updated)),
        now_iso=lambda: "2026-04-04T12:00:00Z",
        delete_requirement_stories=lambda normalized_requirement: 3,
        reset_subject_working_set=_reset_subject_working_set,
    )

    assert payload == {
        "parent_requirement": "Requirement A",
        "data": {
            "deleted_count": 3,
            "message": "Stories deleted successfully",
        },
    }
    assert parent_requirement not in state["story_saved"]
    assert parent_requirement not in state["story_outputs"]
    assert len(state["story_attempts"][parent_requirement]) == 1
    assert state["story_attempts"][parent_requirement][0]["trigger"] == "manual_refine"
    runtime = state["interview_runtime"]["story"][parent_requirement]
    assert runtime["draft_projection"] == {}
    assert runtime["request_projection"] == {}
    assert runtime["feedback_projection"]["items"] == []
    assert len(runtime["attempt_history"]) == 2
    assert runtime["attempt_history"][-1]["trigger"] == "reset"
    assert runtime["attempt_history"][-1]["classification"] == "reset_marker"
    assert "state reset by user" in runtime["attempt_history"][-1]["summary"]
    assert state["another_req"] == "should not be touched"
    assert len(saved_states) == 1


@pytest.mark.asyncio
async def test_delete_story_requirement_rejects_unknown_requirement_before_repo_delete():
    state = {
        "story_saved": {"Requirement A": True},
        "story_outputs": {"Requirement A": {"data": "some artifact"}},
        "story_attempts": {"Requirement A": []},
        "interview_runtime": {"story": {"Requirement A": {"attempt_history": []}}},
    }
    delete_called = False

    def delete_requirement_stories(_normalized_requirement: str) -> int:
        nonlocal delete_called
        delete_called = True
        return 1

    with pytest.raises(StoryPhaseError) as exc_info:
        await delete_story_requirement(
            parent_requirement="  Missing Requirement  ",
            load_state=lambda: _async_value(state),
            save_state=lambda updated: None,
            now_iso=lambda: "2026-04-04T12:00:00Z",
            delete_requirement_stories=delete_requirement_stories,
            reset_subject_working_set=_reset_subject_working_set,
        )

    assert exc_info.value.status_code == 400
    assert delete_called is False


def _reset_subject_working_set(runtime, *, created_at: str, summary: str):
    runtime["draft_projection"] = {}
    runtime["request_projection"] = {}
    runtime["feedback_projection"] = {"items": [], "next_feedback_sequence": 0}
    attempts = list(runtime.get("attempt_history") or [])
    attempts.append(
        {
            "attempt_id": f"reset-marker-{len(attempts) + 1}",
            "created_at": created_at,
            "trigger": "reset",
            "classification": "reset_marker",
            "is_reusable": False,
            "retryable": False,
            "summary": summary,
            "output_artifact": None,
        }
    )
    runtime["attempt_history"] = attempts


async def _async_value(value):
    return value
