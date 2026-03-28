from __future__ import annotations

from services import interview_runtime


def test_ensure_interview_subject_initializes_empty_projection() -> None:
    state: dict[str, object] = {}

    runtime = interview_runtime.ensure_interview_subject(
        state,
        phase="story",
        subject_key="req-1",
    )

    assert runtime == {
        "phase": "story",
        "subject_key": "req-1",
        "attempt_history": [],
        "draft_projection": {},
        "feedback_projection": {"items": []},
        "request_projection": {},
    }
    assert state == {
        "interview_runtime": {
            "story": {
                "req-1": runtime,
            }
        }
    }


def test_append_feedback_and_mark_absorbed() -> None:
    state: dict[str, object] = {}
    runtime = interview_runtime.ensure_interview_subject(
        state,
        phase="story",
        subject_key="req-1",
    )

    entry = interview_runtime.append_feedback_entry(
        runtime,
        text="tighten the scope",
        created_at="2026-03-28T10:00:00Z",
    )

    assert entry == {
        "feedback_id": "feedback-1",
        "text": "tighten the scope",
        "created_at": "2026-03-28T10:00:00Z",
        "status": "unabsorbed",
        "absorbed_by_attempt_id": None,
    }
    assert runtime["feedback_projection"]["items"] == [entry]

    absorbed = interview_runtime.mark_feedback_absorbed(
        runtime,
        feedback_ids=["feedback-1"],
        attempt_id="attempt-1",
    )

    assert absorbed == [entry]
    assert runtime["feedback_projection"]["items"][0] == {
        "feedback_id": "feedback-1",
        "text": "tighten the scope",
        "created_at": "2026-03-28T10:00:00Z",
        "status": "absorbed",
        "absorbed_by_attempt_id": "attempt-1",
    }


def test_hydrate_story_runtime_from_legacy_attempts_promotes_latest_reusable_artifact() -> None:
    state: dict[str, object] = {
        "story_attempts": {
            "req-1": [
                {
                    "failure_stage": "output_validation",
                    "error": "schema mismatch",
                },
                {
                    "failure_stage": "invocation_exception",
                    "error": "provider timeout",
                },
                {
                    "output_artifact": {
                        "user_stories": [
                            {"story_title": "Reusable v1"},
                        ]
                    },
                    "is_complete": False,
                },
                {
                    "output_artifact": {
                        "user_stories": [
                            {"story_title": "Reusable v2"},
                        ]
                    },
                    "is_complete": True,
                },
            ]
        }
    }

    runtime = interview_runtime.hydrate_story_runtime_from_legacy(
        state,
        parent_requirement="req-1",
    )

    assert runtime["attempt_history"][0]["attempt_id"] == "legacy-1"
    assert runtime["attempt_history"][1]["attempt_id"] == "legacy-2"
    assert runtime["attempt_history"][2]["attempt_id"] == "legacy-3"
    assert runtime["attempt_history"][3]["attempt_id"] == "legacy-4"
    assert [attempt["classification"] for attempt in runtime["attempt_history"]] == [
        "nonreusable_schema_failure",
        "nonreusable_provider_failure",
        "reusable_content_result",
        "reusable_content_result",
    ]
    assert runtime["draft_projection"] == {
        "latest_reusable_attempt_id": "legacy-4",
        "kind": "complete_draft",
        "is_complete": True,
        "updated_at": None,
    }

    state["story_attempts"]["req-1"] = []
    hydrated_again = interview_runtime.hydrate_story_runtime_from_legacy(
        state,
        parent_requirement="req-1",
    )
    assert hydrated_again is runtime
    assert len(runtime["attempt_history"]) == 4

    empty_state: dict[str, object] = {}
    empty_runtime = interview_runtime.ensure_interview_subject(
        empty_state,
        phase="story",
        subject_key="req-2",
    )
    hydrated_empty = interview_runtime.hydrate_story_runtime_from_legacy(
        empty_state,
        parent_requirement="req-2",
    )
    assert hydrated_empty is empty_runtime
    assert hydrated_empty["attempt_history"] == []


def test_reset_subject_working_set_clears_projections_and_keeps_audit_marker() -> None:
    state: dict[str, object] = {}
    runtime = interview_runtime.ensure_interview_subject(
        state,
        phase="story",
        subject_key="req-1",
    )

    request_projection = interview_runtime.set_request_projection(
        runtime,
        request_snapshot_id="snapshot-1",
        payload={"prompt": "initial"},
        request_hash="hash-1",
        created_at="2026-03-28T10:00:00Z",
        draft_basis_attempt_id="attempt-1",
        included_feedback_ids=["fb-1"],
        context_version=2,
    )
    assert request_projection == {
        "request_snapshot_id": "snapshot-1",
        "payload": {"prompt": "initial"},
        "request_hash": "hash-1",
        "created_at": "2026-03-28T10:00:00Z",
        "draft_basis_attempt_id": "attempt-1",
        "included_feedback_ids": ["fb-1"],
        "context_version": 2,
    }
    interview_runtime.append_feedback_entry(
        runtime,
        text="refine the prompt",
        created_at="2026-03-28T10:01:00Z",
    )
    interview_runtime.append_attempt(
        runtime,
        {
            "attempt_id": "attempt-1",
            "classification": "reusable_content_result",
            "output_artifact": {
                "user_stories": [
                    {"story_title": "Reusable"},
                ]
            },
        },
    )
    runtime["audit_marker"] = {"kind": "audit", "marker": "keep-me"}

    interview_runtime.reset_subject_working_set(
        runtime,
        created_at="2026-03-28T10:02:00Z",
        summary="reset for next pass",
    )

    assert runtime["request_projection"] == {}
    assert runtime["feedback_projection"]["items"] == []
    assert runtime["draft_projection"] == {}
    assert runtime["attempt_history"][-1]["attempt_id"] == "reset-marker-2"
    assert runtime["attempt_history"][-1]["created_at"] == "2026-03-28T10:02:00Z"
    assert runtime["attempt_history"][-1]["trigger"] == "reset"
    assert runtime["attempt_history"][-1]["classification"] == "reset_marker"
    assert runtime["attempt_history"][-1]["is_reusable"] is False
    assert runtime["attempt_history"][-1]["retryable"] is False
    assert runtime["attempt_history"][-1]["summary"] == "reset for next pass"
    assert runtime["attempt_history"][-1]["output_artifact"] is None
    assert runtime["audit_marker"] == {"kind": "audit", "marker": "keep-me"}
