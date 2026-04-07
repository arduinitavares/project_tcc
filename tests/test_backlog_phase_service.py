from types import SimpleNamespace

import pytest

from services.phases.backlog_service import (
    BacklogPhaseError,
    backlog_state_from_complete,
    ensure_backlog_attempts,
    generate_backlog_draft,
    get_backlog_history,
    record_backlog_attempt,
    save_backlog_draft,
    set_backlog_fsm_state,
)


def test_backlog_state_from_complete_maps_to_review_and_interview():
    assert backlog_state_from_complete(True) == "BACKLOG_REVIEW"
    assert backlog_state_from_complete(False) == "BACKLOG_INTERVIEW"


def test_record_backlog_attempt_updates_working_state():
    state = {}

    count = record_backlog_attempt(
        state,
        trigger="manual_refine",
        input_context={"user_raw_text": "refine"},
        output_artifact={
            "backlog_items": [{"title": "Seed backlog item"}],
            "is_complete": False,
        },
        is_complete=False,
        failure_meta={"failure_stage": "output_validation"},
        created_at="2026-04-04T00:00:00Z",
    )

    assert count == 1
    assert state["backlog_last_input_context"] == {
        "user_raw_text": "refine"
    }
    assert state["product_backlog_assessment"]["backlog_items"][0]["title"] == (
        "Seed backlog item"
    )
    assert state["backlog_items"][0]["title"] == "Seed backlog item"
    assert state["backlog_attempts"][0]["failure_stage"] == "output_validation"


def test_set_backlog_fsm_state_updates_state():
    state = {}

    next_state = set_backlog_fsm_state(
        state,
        is_complete=True,
        now_iso=lambda: "2026-04-04T00:00:00Z",
    )

    assert next_state == "BACKLOG_REVIEW"
    assert state["fsm_state"] == "BACKLOG_REVIEW"
    assert state["fsm_state_entered_at"] == "2026-04-04T00:00:00Z"


def test_ensure_backlog_attempts_returns_existing_list():
    attempts = [{"created_at": "2026-04-04T00:00:00Z"}]
    state = {"backlog_attempts": attempts}

    assert ensure_backlog_attempts(state) is attempts


@pytest.mark.asyncio
async def test_generate_backlog_draft_allows_empty_input_on_first_attempt():
    state = {"fsm_state": "VISION_PERSISTENCE"}
    saved: dict[str, object] = {}
    captured: dict[str, object] = {}

    async def load_state() -> dict[str, object]:
        return state

    def save_state(updated: dict[str, object]) -> None:
        saved["state"] = dict(updated)

    async def fake_run_backlog_agent(state, *, project_id, user_input):
        captured["state"] = state
        captured["project_id"] = project_id
        captured["user_input"] = user_input
        return {
            "success": True,
            "input_context": {"user_input": user_input or ""},
            "output_artifact": {
                "backlog_items": [{"title": "Seed backlog item"}],
                "is_complete": False,
            },
            "is_complete": False,
            "error": None,
            "failure_artifact_id": None,
            "failure_stage": None,
            "failure_summary": None,
            "raw_output_preview": None,
            "has_full_artifact": False,
        }

    payload = await generate_backlog_draft(
        project_id=7,
        load_state=load_state,
        save_state=save_state,
        now_iso=lambda: "2026-04-04T00:00:00Z",
        run_backlog_agent=fake_run_backlog_agent,
        user_input=None,
    )

    assert captured["user_input"] == ""
    assert payload["trigger"] == "auto_transition"
    assert payload["fsm_state"] == "BACKLOG_INTERVIEW"
    assert payload["attempt_count"] == 1
    assert saved["state"]["backlog_attempts"][0]["trigger"] == "auto_transition"


@pytest.mark.asyncio
async def test_generate_backlog_draft_requires_feedback_after_first_attempt():
    state = {
        "fsm_state": "BACKLOG_INTERVIEW",
        "backlog_attempts": [{"created_at": "2026-04-03T00:00:00Z"}],
    }

    async def load_state() -> dict[str, object]:
        return state

    async def fake_run_backlog_agent(**_kwargs):
        raise AssertionError("runner should not be called")

    with pytest.raises(BacklogPhaseError) as exc_info:
        await generate_backlog_draft(
            project_id=7,
            load_state=load_state,
            save_state=lambda _state: None,
            now_iso=lambda: "2026-04-04T00:00:00Z",
            run_backlog_agent=fake_run_backlog_agent,
            user_input="   ",
        )

    assert exc_info.value.status_code == 409
    assert "Feedback is required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_backlog_draft_rejects_setup_required_state():
    state = {"fsm_state": "SETUP_REQUIRED"}

    async def load_state() -> dict[str, object]:
        return state

    async def fake_run_backlog_agent(**_kwargs):
        raise AssertionError("runner should not be called")

    with pytest.raises(BacklogPhaseError) as exc_info:
        await generate_backlog_draft(
            project_id=7,
            load_state=load_state,
            save_state=lambda _state: None,
            now_iso=lambda: "2026-04-04T00:00:00Z",
            run_backlog_agent=fake_run_backlog_agent,
            user_input="input",
        )

    assert exc_info.value.status_code == 409
    assert "Setup required before backlog" in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_backlog_draft_normalizes_legacy_fsm_state():
    state = {"fsm_state": " backlog_interview "}

    async def load_state() -> dict[str, object]:
        return state

    async def fake_run_backlog_agent(state, *, project_id, user_input):
        return {
            "success": True,
            "input_context": {"user_input": user_input or ""},
            "output_artifact": {
                "backlog_items": [{"title": "Seed backlog item"}],
                "is_complete": False,
            },
            "is_complete": False,
            "error": None,
            "failure_artifact_id": None,
            "failure_stage": None,
            "failure_summary": None,
            "raw_output_preview": None,
            "has_full_artifact": False,
        }

    payload = await generate_backlog_draft(
        project_id=7,
        load_state=load_state,
        save_state=lambda _state: None,
        now_iso=lambda: "2026-04-04T00:00:00Z",
        run_backlog_agent=fake_run_backlog_agent,
        user_input="refine",
    )

    assert payload["fsm_state"] == "BACKLOG_INTERVIEW"


@pytest.mark.asyncio
async def test_get_backlog_history_returns_count_and_items():
    state = {
        "backlog_attempts": [
            {"created_at": "2026-04-03T00:00:00Z", "trigger": "manual_refine"}
        ]
    }

    payload = await get_backlog_history(load_state=lambda: _async_value(state))

    assert payload["count"] == 1
    assert payload["items"][0]["trigger"] == "manual_refine"


@pytest.mark.asyncio
async def test_save_backlog_draft_requires_complete_assessment():
    state = {
        "product_backlog_assessment": {
            "backlog_items": [{"title": "Seed backlog item"}],
            "is_complete": False,
        }
    }

    async def hydrate_context():
        return SimpleNamespace(state=dict(state))

    with pytest.raises(BacklogPhaseError) as exc_info:
        await save_backlog_draft(
            project_id=7,
            project_name="Backlog Project",
            save_state=lambda _state: None,
            now_iso=lambda: "2026-04-04T00:00:00Z",
            hydrate_context=hydrate_context,
            build_tool_context=lambda context: context,
            save_backlog_tool=_fake_save_backlog_tool,
        )

    assert exc_info.value.status_code == 409
    assert "is_complete is true" in exc_info.value.detail


@pytest.mark.asyncio
async def test_save_backlog_draft_rejects_empty_items():
    state = {
        "product_backlog_assessment": {
            "backlog_items": [],
            "is_complete": True,
        }
    }

    async def hydrate_context():
        return SimpleNamespace(state=dict(state))

    with pytest.raises(BacklogPhaseError) as exc_info:
        await save_backlog_draft(
            project_id=7,
            project_name="Backlog Project",
            save_state=lambda _state: None,
            now_iso=lambda: "2026-04-04T00:00:00Z",
            hydrate_context=hydrate_context,
            build_tool_context=lambda context: context,
            save_backlog_tool=_fake_save_backlog_tool,
        )

    assert exc_info.value.status_code == 409
    assert "Backlog items are empty" in exc_info.value.detail


@pytest.mark.asyncio
async def test_save_backlog_draft_persists_persistence_state():
    state = {
        "product_backlog_assessment": {
            "backlog_items": [{"title": "Seed backlog item"}],
            "is_complete": True,
        },
        "setup_status": "failed",
    }
    saved: dict[str, object] = {}
    captured: dict[str, object] = {}

    async def hydrate_context():
        context = SimpleNamespace(state=dict(state), session_id="7")
        return context

    def save_state(updated: dict[str, object]) -> None:
        saved["state"] = dict(updated)

    def fake_save_backlog_tool(backlog_input, tool_context):
        captured["backlog_input"] = backlog_input
        captured["tool_context"] = tool_context
        return {
            "success": True,
            "product_id": backlog_input.product_id,
            "saved_count": len(backlog_input.backlog_items),
        }

    payload = await save_backlog_draft(
        project_id=7,
        project_name="Backlog Project",
        save_state=save_state,
        now_iso=lambda: "2026-04-04T00:00:00Z",
        hydrate_context=hydrate_context,
        build_tool_context=lambda context: context,
        save_backlog_tool=fake_save_backlog_tool,
    )

    assert payload["fsm_state"] == "BACKLOG_PERSISTENCE"
    assert payload["save_result"]["success"] is True
    assert captured["backlog_input"].product_id == 7
    assert saved["state"]["fsm_state"] == "BACKLOG_PERSISTENCE"
    assert saved["state"]["backlog_saved_at"] == "2026-04-04T00:00:00Z"


async def _async_value(value):
    return value


def _fake_save_backlog_tool(*_args, **_kwargs):
    raise AssertionError("save_backlog_tool should not be called")
