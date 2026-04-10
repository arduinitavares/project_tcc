"""Backlog phase application service helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, cast

from orchestrator_agent.agent_tools.backlog_primer.tools import SaveBacklogInput
from orchestrator_agent.fsm.states import OrchestratorState
from services.phases import workflow_state

VALID_BACKLOG_GENERATION_STATES = {
    OrchestratorState.VISION_PERSISTENCE.value,
    OrchestratorState.BACKLOG_INTERVIEW.value,
    OrchestratorState.BACKLOG_REVIEW.value,
    OrchestratorState.BACKLOG_PERSISTENCE.value,
    OrchestratorState.ROADMAP_INTERVIEW.value,
}
VALID_FSM_STATES = {state.value for state in OrchestratorState}


class BacklogPhaseError(Exception):
    """Domain-level backlog phase error for router translation."""

    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _normalize_fsm_state(value: str | None) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in VALID_FSM_STATES:
            return normalized
    return OrchestratorState.SETUP_REQUIRED.value


def backlog_state_from_complete(is_complete: bool) -> str:
    return workflow_state.phase_state_from_complete(
        is_complete,
        review_state=OrchestratorState.BACKLOG_REVIEW.value,
        interview_state=OrchestratorState.BACKLOG_INTERVIEW.value,
    )


def ensure_backlog_attempts(state: dict[str, Any]) -> list[dict[str, Any]]:
    return workflow_state.ensure_phase_attempts(
        state,
        attempts_key="backlog_attempts",
    )


def record_backlog_attempt(
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
        attempts_key="backlog_attempts",
        last_input_context_key="backlog_last_input_context",
        assessment_key="product_backlog_assessment",
        trigger=trigger,
        input_context=input_context,
        output_artifact=output_artifact,
        is_complete=is_complete,
        created_at=created_at,
        failure_source=failure_meta,
        mirrored_output_field="backlog_items",
        mirrored_state_key="backlog_items",
        mirrored_output_types=(list,),
    )


def set_backlog_fsm_state(
    state: dict[str, Any],
    *,
    is_complete: bool,
    now_iso: Callable[[], str],
) -> str:
    return workflow_state.set_phase_fsm_state(
        state,
        is_complete=is_complete,
        now_iso=now_iso,
        review_state=OrchestratorState.BACKLOG_REVIEW.value,
        interview_state=OrchestratorState.BACKLOG_INTERVIEW.value,
    )


async def generate_backlog_draft(
    *,
    project_id: int,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
    run_backlog_agent: Callable[..., Awaitable[dict[str, Any]]],
    user_input: str | None,
) -> dict[str, Any]:
    state = await load_state()
    fsm_state = _normalize_fsm_state(state.get("fsm_state"))
    if fsm_state == OrchestratorState.SETUP_REQUIRED.value:
        raise BacklogPhaseError("Setup required before backlog")

    if fsm_state not in VALID_BACKLOG_GENERATION_STATES:
        raise BacklogPhaseError(f"Invalid FSM State for backlog: {fsm_state}")

    attempts = ensure_backlog_attempts(state)
    has_attempts = len(attempts) > 0
    normalized_user_input = (user_input or "").strip()
    if has_attempts and not normalized_user_input:
        raise BacklogPhaseError(
            "Feedback is required for Backlog refinement attempts",
        )

    backlog_result = await run_backlog_agent(
        state,
        project_id=project_id,
        user_input=normalized_user_input,
    )
    is_complete = (
        bool(backlog_result.get("is_complete"))
        if backlog_result.get("success")
        else False
    )

    attempt_count = record_backlog_attempt(
        state,
        trigger="manual_refine" if has_attempts else "auto_transition",
        input_context=backlog_result.get("input_context") or {},
        output_artifact=backlog_result.get("output_artifact") or {},
        is_complete=is_complete,
        failure_meta=backlog_result,
        created_at=now_iso(),
    )
    next_state = set_backlog_fsm_state(
        state,
        is_complete=is_complete,
        now_iso=now_iso,
    )
    save_state(state)

    return {
        "fsm_state": next_state,
        "is_complete": is_complete,
        "backlog_run_success": bool(backlog_result.get("success")),
        "error": backlog_result.get("error"),
        "trigger": "manual_refine" if has_attempts else "auto_transition",
        "input_context": backlog_result.get("input_context"),
        "output_artifact": backlog_result.get("output_artifact"),
        "attempt_count": attempt_count,
        **workflow_state.failure_meta(
            backlog_result, fallback_summary=backlog_result.get("error")
        ),
    }


async def get_backlog_history(
    *,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    state = await load_state()
    attempts = ensure_backlog_attempts(state)
    return {
        "items": attempts,
        "count": len(attempts),
    }


async def save_backlog_draft(
    *,
    project_id: int,
    project_name: str,
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
    hydrate_context: Callable[[], Awaitable[Any]],
    build_tool_context: Callable[[Any], Any],
    save_backlog_tool: Callable[
        [SaveBacklogInput, Any],
        dict[str, Any] | Awaitable[dict[str, Any]],
    ],
) -> dict[str, Any]:
    _ = project_name
    context = await hydrate_context()
    assessment = context.state.get("product_backlog_assessment")
    if not isinstance(assessment, dict):
        raise BacklogPhaseError("No backlog draft available to save")

    if not bool(assessment.get("is_complete", False)):
        raise BacklogPhaseError("Backlog cannot be saved until is_complete is true")

    items = assessment.get("backlog_items")
    if not isinstance(items, list) or len(items) == 0:
        raise BacklogPhaseError("Backlog items are empty")

    result = save_backlog_tool(
        SaveBacklogInput(
            product_id=project_id,
            backlog_items=items,
        ),
        build_tool_context(context),
    )
    if inspect.isawaitable(result):
        result = await result
    result = cast("dict[str, Any]", result)

    if not result.get("success"):
        raise BacklogPhaseError(
            result.get("error", "Failed to save backlog"),
            status_code=500,
        )

    context.state["fsm_state"] = OrchestratorState.BACKLOG_PERSISTENCE.value
    context.state["fsm_state_entered_at"] = now_iso()
    context.state["backlog_saved_at"] = now_iso()
    save_state(context.state)

    return {
        "fsm_state": OrchestratorState.BACKLOG_PERSISTENCE.value,
        "save_result": result,
    }


__all__ = [
    "BacklogPhaseError",
    "backlog_state_from_complete",
    "ensure_backlog_attempts",
    "generate_backlog_draft",
    "get_backlog_history",
    "record_backlog_attempt",
    "save_backlog_draft",
    "set_backlog_fsm_state",
]
