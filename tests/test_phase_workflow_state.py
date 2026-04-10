from orchestrator_agent.fsm.states import OrchestratorState
from services.phases import workflow_state


def test_failure_meta_uses_fallback_summary_when_source_summary_missing():
    payload = workflow_state.failure_meta(
        {
            "failure_artifact_id": "artifact-1",
            "failure_stage": "parser",
            "error": "outer error",
            "raw_output_preview": "{broken}",
        },
        fallback_summary="fallback summary",
    )

    assert payload == {
        "failure_artifact_id": "artifact-1",
        "failure_stage": "parser",
        "failure_summary": "fallback summary",
        "raw_output_preview": "{broken}",
        "has_full_artifact": False,
    }


def test_sprint_state_helpers_delegate_to_shared_workflow_state(monkeypatch):
    from services.phases import sprint_service

    called: dict[str, object] = {}

    def fake_set_phase_fsm_state(state, **kwargs):
        called["kwargs"] = kwargs
        next_state = (
            kwargs["review_state"]
            if kwargs["is_complete"]
            else kwargs["interview_state"]
        )
        state["fsm_state"] = next_state
        state["fsm_state_entered_at"] = kwargs["now_iso"]()
        return next_state

    monkeypatch.setattr(workflow_state, "set_phase_fsm_state", fake_set_phase_fsm_state)

    assert (
        workflow_state.sprint_state_from_complete(True)
        == OrchestratorState.SPRINT_DRAFT.value
    )
    assert (
        workflow_state.sprint_state_from_complete(False)
        == OrchestratorState.SPRINT_SETUP.value
    )

    state: dict[str, object] = {}
    next_state = workflow_state.set_sprint_fsm_state(
        state,
        is_complete=False,
        now_iso=lambda: "2026-04-04T00:00:00Z",
    )

    assert next_state == OrchestratorState.SPRINT_SETUP.value
    assert called["kwargs"]["review_state"] == OrchestratorState.SPRINT_DRAFT.value
    assert called["kwargs"]["interview_state"] == OrchestratorState.SPRINT_SETUP.value
    assert state["fsm_state"] == OrchestratorState.SPRINT_SETUP.value
    assert state["fsm_state_entered_at"] == "2026-04-04T00:00:00Z"
    assert sprint_service.ensure_sprint_attempts({}) == []


def test_record_phase_attempt_mirrors_output_and_updates_state():
    state: dict[str, object] = {}

    count = workflow_state.record_phase_attempt(
        state,
        attempts_key="vision_attempts",
        last_input_context_key="vision_last_input_context",
        assessment_key="product_vision_assessment",
        trigger="manual_refine",
        input_context={"user_raw_text": "refine"},
        output_artifact={
            "updated_components": {"project_name": "Vision Project"},
            "product_vision_statement": "A clear vision.",
            "is_complete": False,
        },
        is_complete=False,
        created_at="2026-04-04T00:00:00Z",
        failure_source={
            "failure_stage": "output_validation",
            "error": "Vision response is not valid JSON",
        },
        failure_summary_fallback="Vision response is not valid JSON",
        mirrored_output_field="updated_components",
        mirrored_state_key="vision_components",
        mirrored_output_types=(dict,),
    )

    assert count == 1
    assert state["vision_last_input_context"] == {"user_raw_text": "refine"}
    assert state["product_vision_assessment"]["product_vision_statement"] == (
        "A clear vision."
    )
    assert state["vision_components"] == {"project_name": "Vision Project"}
    assert state["vision_attempts"][0]["failure_summary"] == (
        "Vision response is not valid JSON"
    )


def test_sprint_attempt_helpers_delegate_to_shared_workflow_state(monkeypatch):
    from services.phases import sprint_service

    ensure_called: dict[str, object] = {}
    record_called: dict[str, object] = {}
    attempts = [{"created_at": "2026-04-04T00:00:00Z"}]

    def fake_ensure_phase_attempts(state, **kwargs):
        ensure_called["kwargs"] = kwargs
        state[kwargs["attempts_key"]] = attempts
        return attempts

    def fake_record_phase_attempt(state, **kwargs):
        record_called["kwargs"] = kwargs
        state[kwargs["attempts_key"]] = [{"created_at": kwargs["created_at"]}]
        state[kwargs["last_input_context_key"]] = kwargs["input_context"]
        state[kwargs["assessment_key"]] = kwargs["output_artifact"]
        return 1

    monkeypatch.setattr(
        workflow_state, "ensure_phase_attempts", fake_ensure_phase_attempts
    )
    monkeypatch.setattr(
        workflow_state, "record_phase_attempt", fake_record_phase_attempt
    )

    state: dict[str, object] = {}
    assert sprint_service.ensure_sprint_attempts(state) is attempts
    assert ensure_called["kwargs"] == {"attempts_key": "sprint_attempts"}

    count = sprint_service.record_sprint_attempt(
        state,
        trigger="manual_refine",
        input_context={"stories": [1]},
        output_artifact={
            "error": "SPRINT_GENERATION_FAILED",
            "validation_errors": [
                " Unsupported task_kind 'other'. ",
                "Unsupported task_kind 'other'.",
            ],
        },
        is_complete=False,
        failure_meta={"failure_stage": "planner"},
        created_at="2026-04-04T00:00:00Z",
    )

    assert count == 1
    assert record_called["kwargs"]["attempts_key"] == "sprint_attempts"
    assert record_called["kwargs"]["output_artifact"]["validation_errors"] == [
        "Unsupported task_kind 'other'. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]


def test_set_phase_fsm_state_preserves_normalized_current_state():
    state = {"fsm_state": " story_review "}

    next_state = workflow_state.set_phase_fsm_state(
        state,
        is_complete=False,
        now_iso=lambda: "2026-04-04T00:00:00Z",
        review_state="ROADMAP_REVIEW",
        interview_state="ROADMAP_INTERVIEW",
        current_state=state["fsm_state"].strip().upper(),
        preserved_states={
            OrchestratorState.STORY_REVIEW.value,
            OrchestratorState.STORY_PERSISTENCE.value,
        },
        persist_current_state=True,
    )

    assert next_state == "STORY_REVIEW"
    assert state["fsm_state"] == "STORY_REVIEW"
    assert "fsm_state_entered_at" not in state


def test_vision_attempt_helpers_delegate_to_shared_workflow_state(
    monkeypatch,
):
    from services.phases import vision_service

    called: dict[str, object] = {}

    def fake_record_phase_attempt(state, **kwargs):
        called["kwargs"] = kwargs
        state[kwargs["attempts_key"]] = [{"created_at": kwargs["created_at"]}]
        state[kwargs["last_input_context_key"]] = kwargs["input_context"]
        state[kwargs["assessment_key"]] = kwargs["output_artifact"]
        mirrored = kwargs["output_artifact"].get(kwargs["mirrored_output_field"])
        if isinstance(mirrored, kwargs["mirrored_output_types"]):
            state[kwargs["mirrored_state_key"]] = mirrored
        return 1

    monkeypatch.setattr(
        workflow_state, "record_phase_attempt", fake_record_phase_attempt
    )

    state: dict[str, object] = {}
    count = vision_service.record_vision_attempt(
        state,
        trigger="manual_refine",
        input_context={"user_raw_text": ""},
        output_artifact={
            "updated_components": {"project_name": "Vision Project"},
            "product_vision_statement": "A clear vision.",
            "is_complete": False,
        },
        is_complete=False,
        failure_meta={
            "failure_stage": "output_validation",
            "error": "Vision response is not valid JSON",
        },
        now_iso=lambda: "2026-04-04T00:00:00Z",
    )

    assert count == 1
    assert called["kwargs"]["attempts_key"] == "vision_attempts"
    assert state["vision_components"] == {"project_name": "Vision Project"}


def test_backlog_attempt_helpers_delegate_to_shared_workflow_state(
    monkeypatch,
):
    from services.phases import backlog_service

    called: dict[str, object] = {}

    def fake_record_phase_attempt(state, **kwargs):
        called["kwargs"] = kwargs
        state[kwargs["attempts_key"]] = [{"created_at": kwargs["created_at"]}]
        state[kwargs["last_input_context_key"]] = kwargs["input_context"]
        state[kwargs["assessment_key"]] = kwargs["output_artifact"]
        mirrored = kwargs["output_artifact"].get(kwargs["mirrored_output_field"])
        if isinstance(mirrored, kwargs["mirrored_output_types"]):
            state[kwargs["mirrored_state_key"]] = mirrored
        return 1

    monkeypatch.setattr(
        workflow_state, "record_phase_attempt", fake_record_phase_attempt
    )

    state: dict[str, object] = {}
    count = backlog_service.record_backlog_attempt(
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
    assert called["kwargs"]["attempts_key"] == "backlog_attempts"
    assert state["backlog_items"][0]["title"] == "Seed backlog item"


def test_roadmap_attempt_helpers_delegate_to_shared_workflow_state(
    monkeypatch,
):
    from services.phases import roadmap_service

    called: dict[str, object] = {}

    def fake_record_phase_attempt(state, **kwargs):
        called["kwargs"] = kwargs
        state[kwargs["attempts_key"]] = [{"created_at": kwargs["created_at"]}]
        state[kwargs["last_input_context_key"]] = kwargs["input_context"]
        state[kwargs["assessment_key"]] = kwargs["output_artifact"]
        mirrored = kwargs["output_artifact"].get(kwargs["mirrored_output_field"])
        if isinstance(mirrored, kwargs["mirrored_output_types"]):
            state[kwargs["mirrored_state_key"]] = mirrored
        return 1

    monkeypatch.setattr(
        workflow_state, "record_phase_attempt", fake_record_phase_attempt
    )

    state: dict[str, object] = {}
    count = roadmap_service.record_roadmap_attempt(
        state,
        trigger="manual_refine",
        input_context={"user_raw_text": "refine"},
        output_artifact={
            "roadmap_releases": [{"release_name": "M1"}],
            "is_complete": False,
        },
        is_complete=False,
        failure_meta={"failure_stage": "output_validation"},
        created_at="2026-04-04T00:00:00Z",
    )

    assert count == 1
    assert called["kwargs"]["attempts_key"] == "roadmap_attempts"
    assert state["roadmap_releases"][0]["release_name"] == "M1"
