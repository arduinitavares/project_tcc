from types import SimpleNamespace

import pytest

from services.phases.sprint_service import (
    SprintPhaseError,
    close_sprint,
    ensure_sprint_attempts,
    generate_sprint_plan,
    get_saved_sprint_detail,
    get_sprint_close_readiness,
    get_sprint_history,
    list_saved_sprints,
    normalize_sprint_output_artifact,
    record_sprint_attempt,
    reset_sprint_planner,
    reset_sprint_planner_working_set,
    reset_stale_saved_sprint_planner_working_set,
    save_sprint_plan,
    start_saved_sprint,
)


def test_record_sprint_attempt_updates_working_state():
    state = {}

    count = record_sprint_attempt(
        state,
        trigger="manual_refine",
        input_context={"stories": [1]},
        output_artifact={"validation_errors": [" Unsupported task_kind 'other'. "]},
        is_complete=False,
        failure_meta={"failure_stage": "planner"},
        created_at="2026-04-04T00:00:00Z",
    )

    assert count == 1
    assert state["sprint_last_input_context"] == {"stories": [1]}
    assert state["sprint_plan_assessment"]["validation_errors"] == [
        state["sprint_plan_assessment"]["validation_errors"][0]
    ]
    assert state["sprint_plan_assessment"]["validation_errors"][0].startswith(
        "Unsupported task_kind 'other'."
    )
    assert state["sprint_attempts"][0]["failure_stage"] == "planner"


def test_reset_stale_saved_sprint_planner_working_set_clears_orphaned_owner():
    state = {
        "sprint_attempts": [{"created_at": "old"}],
        "sprint_last_input_context": {"stories": [1]},
        "sprint_plan_assessment": {"draft": True},
        "sprint_saved_at": "2026-04-01T00:00:00Z",
        "sprint_planner_owner_sprint_id": 9,
    }

    changed = reset_stale_saved_sprint_planner_working_set(
        state,
        current_planned_sprint_id=11,
    )

    assert changed is True
    assert state["sprint_attempts"] == []
    assert state["sprint_plan_assessment"] is None


def test_reset_stale_saved_sprint_planner_working_set_keeps_current_owner():
    state = {"sprint_planner_owner_sprint_id": 11}

    changed = reset_stale_saved_sprint_planner_working_set(
        state,
        current_planned_sprint_id=11,
    )

    assert changed is False


def test_ensure_sprint_attempts_returns_existing_list():
    attempts = [{"created_at": "2026-04-04T00:00:00Z"}]
    state = {"sprint_attempts": attempts}

    assert ensure_sprint_attempts(state) is attempts


def test_reset_sprint_planner_working_set_clears_transient_fields():
    state = {
        "sprint_attempts": [{"created_at": "old"}],
        "sprint_last_input_context": {"stories": [1]},
        "sprint_plan_assessment": {"draft": True},
        "sprint_saved_at": "2026-04-01T00:00:00Z",
        "sprint_planner_owner_sprint_id": 9,
    }

    reset_sprint_planner_working_set(state)

    assert state == {
        "sprint_attempts": [],
        "sprint_last_input_context": None,
        "sprint_plan_assessment": None,
        "sprint_saved_at": None,
        "sprint_planner_owner_sprint_id": None,
    }


def test_normalize_sprint_output_artifact_deduplicates_validation_hints():
    payload = normalize_sprint_output_artifact(
        {
            "validation_errors": [
                " Unsupported task_kind 'other'. ",
                "Unsupported task_kind 'other'.",
            ]
        }
    )

    assert len(payload["validation_errors"]) == 1
    assert payload["validation_errors"][0].startswith("Unsupported task_kind 'other'.")


def _failure_meta_builder(
    source: dict[str, object] | None, fallback_summary: str | None = None
) -> dict[str, object]:
    payload = source or {}
    return {
        "failure_artifact_id": payload.get("failure_artifact_id"),
        "failure_stage": payload.get("failure_stage"),
        "failure_summary": payload.get("failure_summary") or fallback_summary,
        "raw_output_preview": payload.get("raw_output_preview"),
        "has_full_artifact": bool(payload.get("has_full_artifact", False)),
    }


@pytest.mark.asyncio
async def test_generate_sprint_plan_updates_state_and_returns_payload():
    state = {"fsm_state": "SPRINT_SETUP"}
    saved: dict[str, object] = {}
    captured: dict[str, object] = {}

    async def load_state() -> dict[str, object]:
        return state

    def save_state(updated: dict[str, object]) -> None:
        saved["state"] = dict(updated)

    async def fake_run_sprint_agent(state, **kwargs):
        captured["state"] = state
        captured.update(kwargs)
        return {
            "success": True,
            "input_context": {"available_stories": [], "note": "ready"},
            "output_artifact": {
                "is_complete": True,
                "validation_errors": [" Unsupported task_kind 'other'. "],
            },
            "is_complete": True,
            "error": None,
        }

    payload = await generate_sprint_plan(
        project_id=7,
        load_state=load_state,
        save_state=save_state,
        current_planned_sprint_id=None,
        now_iso=lambda: "2026-04-04T00:00:00Z",
        run_sprint_agent=fake_run_sprint_agent,
        failure_meta_builder=_failure_meta_builder,
        team_velocity_assumption="Medium",
        sprint_duration_days=14,
        max_story_points=13,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input="Focus on persistence",
    )

    assert payload["fsm_state"] == "SPRINT_DRAFT"
    assert payload["attempt_count"] == 1
    assert payload["trigger"] == "auto_transition"
    assert payload["output_artifact"]["validation_errors"][0].startswith(
        "Unsupported task_kind 'other'."
    )
    assert state["fsm_state"] == "SPRINT_DRAFT"
    assert state["fsm_state_entered_at"] == "2026-04-04T00:00:00Z"
    assert state["sprint_attempts"][0]["trigger"] == "auto_transition"
    assert captured["project_id"] == 7
    assert captured["selected_story_ids"] == [12]


@pytest.mark.asyncio
async def test_generate_sprint_plan_uses_shared_fsm_transition_helper():
    from services.phases import workflow_state

    state = {"fsm_state": "SPRINT_SETUP"}
    saved: dict[str, object] = {}
    called: dict[str, object] = {}

    async def load_state() -> dict[str, object]:
        return state

    def save_state(updated: dict[str, object]) -> None:
        saved["state"] = dict(updated)

    async def fake_run_sprint_agent(state, **kwargs):
        called["agent_kwargs"] = kwargs
        return {
            "success": True,
            "input_context": {"available_stories": [], "note": "ready"},
            "output_artifact": {"is_complete": False},
            "is_complete": False,
            "error": None,
        }

    def fake_set_sprint_fsm_state(state, *, is_complete, now_iso):
        called["fsm_kwargs"] = {
            "is_complete": is_complete,
            "now_iso": now_iso(),
        }
        next_state = "SPRINT_DRAFT" if is_complete else "SPRINT_SETUP"
        state["fsm_state"] = next_state
        state["fsm_state_entered_at"] = called["fsm_kwargs"]["now_iso"]
        return next_state

    original = workflow_state.set_sprint_fsm_state
    workflow_state.set_sprint_fsm_state = fake_set_sprint_fsm_state
    try:
        payload = await generate_sprint_plan(
            project_id=7,
            load_state=load_state,
            save_state=save_state,
            current_planned_sprint_id=None,
            now_iso=lambda: "2026-04-04T00:00:00Z",
            run_sprint_agent=fake_run_sprint_agent,
            failure_meta_builder=_failure_meta_builder,
            team_velocity_assumption="Medium",
            sprint_duration_days=14,
            max_story_points=None,
            include_task_decomposition=True,
            selected_story_ids=None,
            user_input=None,
        )
    finally:
        workflow_state.set_sprint_fsm_state = original

    assert payload["fsm_state"] == "SPRINT_SETUP"
    assert payload["attempt_count"] == 1
    assert called["fsm_kwargs"]["is_complete"] is False
    assert state["fsm_state"] == "SPRINT_SETUP"
    assert saved["state"]["fsm_state_entered_at"] == "2026-04-04T00:00:00Z"


@pytest.mark.asyncio
async def test_generate_sprint_plan_rejects_invalid_fsm_state():
    state = {"fsm_state": "VISION_REVIEW"}

    async def load_state() -> dict[str, object]:
        return state

    async def fake_run_sprint_agent(**_kwargs):
        raise AssertionError("runner should not be called")

    with pytest.raises(SprintPhaseError) as exc_info:
        await generate_sprint_plan(
            project_id=7,
            load_state=load_state,
            save_state=lambda _state: None,
            current_planned_sprint_id=None,
            now_iso=lambda: "2026-04-04T00:00:00Z",
            run_sprint_agent=fake_run_sprint_agent,
            failure_meta_builder=_failure_meta_builder,
            team_velocity_assumption="Medium",
            sprint_duration_days=14,
            max_story_points=None,
            include_task_decomposition=True,
            selected_story_ids=None,
            user_input=None,
        )

    assert exc_info.value.status_code == 409
    assert "Invalid phase for sprint generation" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_sprint_history_normalizes_and_persists_legacy_attempts():
    state = {
        "sprint_attempts": [
            {
                "created_at": "2026-03-29T12:00:00Z",
                "trigger": "manual_refine",
                "input_context": {"available_stories": []},
                "output_artifact": {
                    "error": "SPRINT_GENERATION_FAILED",
                    "validation_errors": [
                        {
                            "loc": [
                                "selected_stories",
                                0,
                                "tasks",
                                0,
                                "task_kind",
                            ],
                            "msg": "Input should be 'analysis', 'design', 'implementation', 'testing', 'documentation', 'refactor' or 'other'",
                            "input": "review",
                        }
                    ],
                },
                "is_complete": False,
            }
        ]
    }
    saves: list[dict[str, object]] = []

    async def load_state() -> dict[str, object]:
        return state

    def save_state(updated: dict[str, object]) -> None:
        saves.append(dict(updated))

    payload = await get_sprint_history(
        load_state=load_state,
        save_state=save_state,
        current_planned_sprint_id=None,
    )

    assert payload["count"] == 1
    assert payload["items"][0]["output_artifact"]["validation_errors"] == [
        "Unsupported task_kind 'review'. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]
    assert len(saves) == 1


@pytest.mark.asyncio
async def test_reset_sprint_planner_rejects_existing_planned_sprint():
    async def load_state() -> dict[str, object]:
        return {"sprint_attempts": [{"created_at": "old"}]}

    with pytest.raises(SprintPhaseError) as exc_info:
        await reset_sprint_planner(
            load_state=load_state,
            save_state=lambda _state: None,
            current_planned_sprint_id=99,
        )

    assert exc_info.value.status_code == 409
    assert "A planned sprint already exists." in exc_info.value.detail


def test_list_saved_sprints_returns_serialized_items_and_runtime_summary():
    sprint_a = SimpleNamespace(sprint_id=1)
    sprint_b = SimpleNamespace(sprint_id=2)

    payload = list_saved_sprints(
        load_sprints=lambda: [sprint_a, sprint_b],
        build_runtime_summary=lambda sprints: {
            "planned_sprint_id": sprints[0].sprint_id,
            "active_sprint_id": None,
        },
        serialize_sprint_list_item=lambda sprint, runtime_summary: {
            "id": sprint.sprint_id,
            "planned_sprint_id": runtime_summary["planned_sprint_id"],
        },
    )

    assert payload == {
        "items": [
            {"id": 1, "planned_sprint_id": 1},
            {"id": 2, "planned_sprint_id": 1},
        ],
        "count": 2,
        "runtime_summary": {
            "planned_sprint_id": 1,
            "active_sprint_id": None,
        },
    }


def test_get_saved_sprint_detail_rejects_missing_sprint():
    with pytest.raises(SprintPhaseError) as exc_info:
        get_saved_sprint_detail(
            load_sprint=lambda: None,
            load_sprints=list,
            build_runtime_summary=lambda _sprints: {},
            serialize_sprint_detail=lambda _sprint, _summary: {},
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Sprint not found"


def test_get_saved_sprint_detail_returns_serialized_detail_and_summary():
    sprint = SimpleNamespace(sprint_id=7)
    all_sprints = [sprint, SimpleNamespace(sprint_id=8)]

    payload = get_saved_sprint_detail(
        load_sprint=lambda: sprint,
        load_sprints=lambda: all_sprints,
        build_runtime_summary=lambda sprints: {
            "planned_sprint_id": sprints[0].sprint_id,
            "latest_completed_sprint_id": sprints[-1].sprint_id,
        },
        serialize_sprint_detail=lambda sprint_obj, runtime_summary: {
            "id": sprint_obj.sprint_id,
            "summary": runtime_summary,
        },
    )

    assert payload == {
        "sprint": {
            "id": 7,
            "summary": {
                "planned_sprint_id": 7,
                "latest_completed_sprint_id": 8,
            },
        },
        "runtime_summary": {
            "planned_sprint_id": 7,
            "latest_completed_sprint_id": 8,
        },
    }


def test_get_sprint_close_readiness_returns_guidance_for_completed_sprint():
    sprint = SimpleNamespace(
        status="Completed",
        completed_at="2026-04-04T12:00:00Z",
    )
    readiness = SimpleNamespace(
        completed_story_count=2,
        open_story_count=0,
        unfinished_story_ids=[],
        stories=[],
    )

    payload = get_sprint_close_readiness(
        sprint_id=7,
        load_sprint=lambda: sprint,
        build_readiness=lambda sprint_obj: readiness,
        history_fidelity=lambda sprint_obj: "snapshotted",
        load_close_snapshot=lambda sprint_obj: {"closed_at": "2026-04-04T12:00:00Z"},
    )

    assert payload["sprint_id"] == 7
    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Sprint is already completed."
    assert payload["history_fidelity"] == "snapshotted"


def test_close_sprint_rejects_non_active_sprint():
    sprint = SimpleNamespace(status="Planned", completed_at=None)

    with pytest.raises(SprintPhaseError) as exc_info:
        close_sprint(
            sprint_id=7,
            completion_notes="Ship it",
            follow_up_notes=None,
            load_sprint=lambda: sprint,
            build_readiness=lambda sprint_obj: SimpleNamespace(
                completed_story_count=0,
                open_story_count=1,
                unfinished_story_ids=[12],
                stories=[],
            ),
            now_iso=lambda: "2026-04-04T12:00:00Z",
            persist_closed_sprint=lambda snapshot: sprint,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only active sprints can be closed."


def test_close_sprint_returns_completed_snapshot_payload():
    story_summary = SimpleNamespace(
        model_dump=lambda mode="json": {"story_id": 12, "story_title": "Done"}
    )
    readiness = SimpleNamespace(
        completed_story_count=1,
        open_story_count=0,
        unfinished_story_ids=[],
        stories=[story_summary],
    )
    sprint = SimpleNamespace(status="Active", completed_at=None)
    closed_sprint = SimpleNamespace(completed_at="2026-04-04T12:34:56Z")

    payload = close_sprint(
        sprint_id=7,
        completion_notes="Closed after review.",
        follow_up_notes="Carry remaining backlog forward manually.",
        load_sprint=lambda: sprint,
        build_readiness=lambda sprint_obj: readiness,
        now_iso=lambda: "2026-04-04T12:00:00Z",
        persist_closed_sprint=lambda snapshot: closed_sprint,
    )

    assert payload["current_status"] == "Completed"
    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Sprint is already completed."
    assert payload["history_fidelity"] == "snapshotted"
    assert payload["close_snapshot"] == {
        "closed_at": "2026-04-04T12:00:00Z",
        "completion_notes": "Closed after review.",
        "follow_up_notes": "Carry remaining backlog forward manually.",
        "completed_story_count": 1,
        "open_story_count": 0,
        "unfinished_story_ids": [],
        "stories": [{"story_id": 12, "story_title": "Done"}],
    }
    assert payload["completed_at"] == "2026-04-04T12:34:56Z"


@pytest.mark.asyncio
async def test_save_sprint_plan_sanitizes_assessment_and_updates_state():
    state = {
        "fsm_state": "SPRINT_DRAFT",
        "sprint_plan_assessment": {
            "sprint_goal": "Persist safely",
            "sprint_number": 1,
            "duration_days": 14,
            "selected_stories": [],
            "deselected_stories": [],
            "capacity_analysis": {
                "velocity_assumption": "Medium",
                "capacity_band": "4-5 stories",
                "selected_count": 0,
                "story_points_used": 0,
                "max_story_points": 13,
                "commitment_note": "Fits",
                "reasoning": "Fits",
            },
            "is_complete": True,
        },
    }
    hydrated_context = SimpleNamespace(
        state={"preserved": True},
        session_id="7",
    )
    saved_states: list[dict[str, object]] = []
    captured: dict[str, object] = {}

    async def load_state() -> dict[str, object]:
        return state

    def save_state(updated: dict[str, object]) -> None:
        saved_states.append(dict(updated))

    async def hydrate_context(session_id: str, project_id: int):
        assert session_id == "7"
        assert project_id == 7
        return hydrated_context

    def build_tool_context(context):
        return context

    def save_plan_tool(input_data, tool_context):
        captured["input_data"] = input_data
        captured["tool_context"] = tool_context
        return {"success": True, "sprint_id": 9}

    payload = await save_sprint_plan(
        project_id=7,
        load_state=load_state,
        save_state=save_state,
        current_planned_sprint_id=None,
        now_iso=lambda: "2026-04-04T00:00:00Z",
        hydrate_context=hydrate_context,
        build_tool_context=build_tool_context,
        save_plan_tool=save_plan_tool,
        team_name="Team Alpha",
        sprint_start_date="2026-03-15",
    )

    assert payload["fsm_state"] == "SPRINT_PERSISTENCE"
    assert payload["save_result"]["sprint_id"] == 9
    assert state["fsm_state"] == "SPRINT_PERSISTENCE"
    assert state["sprint_saved_at"] == "2026-04-04T00:00:00Z"
    assert state["sprint_planner_owner_sprint_id"] == 9
    assert captured["input_data"].team_name == "Team Alpha"
    assert captured["input_data"].sprint_start_date == "2026-03-15"
    assert captured["tool_context"].state["sprint_plan"]["duration_days"] == 14
    assert "is_complete" not in captured["tool_context"].state["sprint_plan"]


@pytest.mark.asyncio
async def test_save_sprint_plan_maps_open_sprint_conflict_to_phase_error():
    state = {
        "fsm_state": "SPRINT_DRAFT",
        "sprint_plan_assessment": {
            "sprint_goal": "Persist safely",
            "sprint_number": 1,
            "duration_days": 14,
            "selected_stories": [],
            "deselected_stories": [],
            "capacity_analysis": {
                "velocity_assumption": "Medium",
                "capacity_band": "4-5 stories",
                "selected_count": 0,
                "story_points_used": 0,
                "max_story_points": 13,
                "commitment_note": "Fits",
                "reasoning": "Fits",
            },
            "is_complete": True,
        },
    }

    async def load_state() -> dict[str, object]:
        return state

    async def hydrate_context(_session_id: str, _project_id: int):
        return SimpleNamespace(state={}, session_id="7")

    def save_plan_tool(_input_data, _tool_context):
        return {
            "success": False,
            "error_code": "STORY_ALREADY_IN_OPEN_SPRINT",
            "error": "Stories already assigned to active or planned sprints: [12]",
        }

    with pytest.raises(SprintPhaseError) as exc_info:
        await save_sprint_plan(
            project_id=7,
            load_state=load_state,
            save_state=lambda _state: None,
            current_planned_sprint_id=None,
            now_iso=lambda: "2026-04-04T00:00:00Z",
            hydrate_context=hydrate_context,
            build_tool_context=lambda context: context,
            save_plan_tool=save_plan_tool,
            team_name="Team Alpha",
            sprint_start_date="2026-03-15",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "Stories already assigned to active or planned sprints: [12]"
    )


def test_start_saved_sprint_rejects_other_active_sprint():
    sprint = SimpleNamespace(status="PLANNED", started_at=None)

    with pytest.raises(SprintPhaseError) as exc_info:
        start_saved_sprint(
            project_id=7,
            sprint_id=3,
            load_sprint=lambda: sprint,
            load_other_active=lambda: object(),
            persist_started_sprint=lambda: sprint,
            build_runtime_summary=dict,
            serialize_sprint=lambda _sprint, _summary: {"id": 3},
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Another sprint is already active for this project."


def test_start_saved_sprint_returns_existing_active_detail_without_persisting():
    sprint = SimpleNamespace(status="ACTIVE", started_at="2026-04-01T09:00:00Z")
    called = {"persist": False}

    payload = start_saved_sprint(
        project_id=7,
        sprint_id=3,
        load_sprint=lambda: sprint,
        load_other_active=lambda: None,
        persist_started_sprint=lambda: called.__setitem__("persist", True),
        build_runtime_summary=lambda: {"active_sprint_id": 3},
        serialize_sprint=lambda _sprint, summary: {"id": 3, "summary": summary},
    )

    assert payload["sprint"]["id"] == 3
    assert payload["sprint"]["summary"] == {"active_sprint_id": 3}
    assert called["persist"] is False


def test_start_saved_sprint_rejects_completed_status_variants():
    sprint = SimpleNamespace(status="Completed", started_at="2026-04-01T09:00:00Z")

    with pytest.raises(SprintPhaseError) as exc_info:
        start_saved_sprint(
            project_id=7,
            sprint_id=3,
            load_sprint=lambda: sprint,
            load_other_active=lambda: None,
            persist_started_sprint=lambda: sprint,
            build_runtime_summary=dict,
            serialize_sprint=lambda _sprint, _summary: {"id": 3},
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Completed sprints cannot be restarted."


def test_start_saved_sprint_persists_planned_sprint_and_returns_detail():
    sprint = SimpleNamespace(status="PLANNED", started_at=None)
    started = SimpleNamespace(status="ACTIVE", started_at="2026-04-01T09:00:00Z")

    payload = start_saved_sprint(
        project_id=7,
        sprint_id=3,
        load_sprint=lambda: sprint,
        load_other_active=lambda: None,
        persist_started_sprint=lambda: started,
        build_runtime_summary=lambda: {"active_sprint_id": 3},
        serialize_sprint=lambda sprint_obj, summary: {
            "status": sprint_obj.status,
            "summary": summary,
        },
    )

    assert payload["sprint"]["status"] == "ACTIVE"
    assert payload["sprint"]["summary"] == {"active_sprint_id": 3}
