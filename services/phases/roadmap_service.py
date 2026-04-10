"""Roadmap phase application service helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from orchestrator_agent.agent_tools.roadmap_builder.schemes import (
    RoadmapBuilderOutput,
)
from orchestrator_agent.agent_tools.roadmap_builder.tools import (
    SaveRoadmapToolInput,
)
from orchestrator_agent.fsm.states import OrchestratorState
from services.phases import workflow_state

_PRESERVED_ROADMAP_STATES = {
    OrchestratorState.ROADMAP_PERSISTENCE.value,
    OrchestratorState.STORY_INTERVIEW.value,
    OrchestratorState.STORY_REVIEW.value,
    OrchestratorState.STORY_PERSISTENCE.value,
    OrchestratorState.SPRINT_SETUP.value,
    OrchestratorState.SPRINT_DRAFT.value,
    OrchestratorState.SPRINT_PERSISTENCE.value,
    OrchestratorState.SPRINT_VIEW.value,
    OrchestratorState.SPRINT_LIST.value,
    OrchestratorState.SPRINT_UPDATE_STORY.value,
    OrchestratorState.SPRINT_MODIFY.value,
    OrchestratorState.SPRINT_COMPLETE.value,
}
_VALID_FSM_STATES = {state.value for state in OrchestratorState}


class RoadmapPhaseError(Exception):
    """Domain-level roadmap phase error for router translation."""

    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _normalize_fsm_state(value: str | None) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in _VALID_FSM_STATES:
            return normalized
    return OrchestratorState.SETUP_REQUIRED.value


def roadmap_state_from_complete(is_complete: bool) -> str:
    return workflow_state.phase_state_from_complete(
        is_complete,
        review_state=OrchestratorState.ROADMAP_REVIEW.value,
        interview_state=OrchestratorState.ROADMAP_INTERVIEW.value,
    )


def ensure_roadmap_attempts(state: dict[str, Any]) -> list[dict[str, Any]]:
    return workflow_state.ensure_phase_attempts(
        state,
        attempts_key="roadmap_attempts",
    )


def record_roadmap_attempt(
    state: dict[str, Any],
    *,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any],
    is_complete: bool,
    created_at: str,
    failure_meta: dict[str, Any] | None = None,
) -> int:
    return workflow_state.record_phase_attempt(
        state,
        attempts_key="roadmap_attempts",
        last_input_context_key="roadmap_last_input_context",
        assessment_key="product_roadmap_assessment",
        trigger=trigger,
        input_context=input_context,
        output_artifact=output_artifact,
        is_complete=is_complete,
        created_at=created_at,
        failure_source=failure_meta,
        mirrored_output_field="roadmap_releases",
        mirrored_state_key="roadmap_releases",
        mirrored_output_types=(list,),
    )


def set_roadmap_fsm_state(
    state: dict[str, Any],
    *,
    is_complete: bool,
    now_iso: Callable[[], str],
) -> str:
    current_state = _normalize_fsm_state(state.get("fsm_state"))
    return workflow_state.set_phase_fsm_state(
        state,
        is_complete=is_complete,
        now_iso=now_iso,
        review_state=OrchestratorState.ROADMAP_REVIEW.value,
        interview_state=OrchestratorState.ROADMAP_INTERVIEW.value,
        current_state=current_state,
        preserved_states=_PRESERVED_ROADMAP_STATES,
        persist_current_state=True,
    )


async def generate_roadmap_draft(
    *,
    project_id: int,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
    run_roadmap_agent: Callable[..., Awaitable[dict[str, Any]]],
    user_input: str | None,
) -> dict[str, Any]:
    state = await load_state()
    attempts = ensure_roadmap_attempts(state)
    has_attempts = len(attempts) > 0
    normalized_user_input = (user_input or "").strip()
    if has_attempts and not normalized_user_input:
        raise RoadmapPhaseError(
            "User input is required to refine an existing roadmap.",
            status_code=400,
        )

    roadmap_result = await run_roadmap_agent(
        state,
        project_id=project_id,
        user_input=normalized_user_input,
    )
    is_complete = (
        bool(roadmap_result.get("is_complete"))
        if roadmap_result.get("success")
        else False
    )
    attempt_count = record_roadmap_attempt(
        state,
        trigger="manual_refine" if has_attempts else "auto_transition",
        input_context=roadmap_result.get("input_context") or {},
        output_artifact=roadmap_result.get("output_artifact") or {},
        is_complete=is_complete,
        failure_meta=roadmap_result,
        created_at=now_iso(),
    )
    next_state = set_roadmap_fsm_state(
        state,
        is_complete=is_complete,
        now_iso=now_iso,
    )
    save_state(state)

    return {
        "fsm_state": next_state,
        "is_complete": is_complete,
        "roadmap_run_success": bool(roadmap_result.get("success")),
        "error": roadmap_result.get("error"),
        "trigger": "manual_refine" if has_attempts else "auto_transition",
        "input_context": roadmap_result.get("input_context"),
        "output_artifact": roadmap_result.get("output_artifact"),
        "attempt_count": attempt_count,
        **workflow_state.failure_meta(
            roadmap_result, fallback_summary=roadmap_result.get("error")
        ),
    }


async def get_roadmap_history(
    *,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    state = await load_state()
    attempts = ensure_roadmap_attempts(state)
    return {
        "items": attempts,
        "count": len(attempts),
    }


async def save_roadmap_draft(
    *,
    project_id: int,
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
    hydrate_context: Callable[[], Awaitable[Any]],
    build_tool_context: Callable[[Any], Any],
    save_roadmap_tool: Callable[[SaveRoadmapToolInput, Any], dict[str, Any]],
) -> dict[str, Any]:
    context = await hydrate_context()
    assessment = context.state.get("product_roadmap_assessment")
    if not isinstance(assessment, dict):
        raise RoadmapPhaseError("No roadmap draft available to save")

    if not bool(assessment.get("is_complete", False)):
        raise RoadmapPhaseError("Roadmap cannot be saved until is_complete is true")

    try:
        roadmap_data = RoadmapBuilderOutput.model_validate(assessment)
    except Exception as exc:  # pylint: disable=broad-except
        raise RoadmapPhaseError(
            f"Invalid roadmap data in session: {exc!s}",
            status_code=500,
        ) from exc

    result = save_roadmap_tool(
        SaveRoadmapToolInput(
            product_id=project_id,
            roadmap_data=roadmap_data,
        ),
        build_tool_context(context),
    )
    if not result.get("success"):
        raise RoadmapPhaseError(
            result.get("error", "Failed to save roadmap"),
            status_code=500,
        )

    context.state["fsm_state"] = OrchestratorState.ROADMAP_PERSISTENCE.value
    context.state["fsm_state_entered_at"] = now_iso()
    context.state["roadmap_saved_at"] = now_iso()
    save_state(context.state)

    return {
        "fsm_state": OrchestratorState.ROADMAP_PERSISTENCE.value,
        "save_result": result,
    }


__all__ = [
    "RoadmapPhaseError",
    "ensure_roadmap_attempts",
    "generate_roadmap_draft",
    "get_roadmap_history",
    "record_roadmap_attempt",
    "roadmap_state_from_complete",
    "save_roadmap_draft",
    "set_roadmap_fsm_state",
]
