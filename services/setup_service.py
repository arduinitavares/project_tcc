"""Application service for project setup orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypedDict, Unpack

from orchestrator_agent.fsm.states import OrchestratorState
from services.phases import workflow_state
from services.phases.vision_service import (
    record_vision_attempt,
    set_vision_fsm_state,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class _SetupWorkflowContext(Protocol):
    state: dict[str, Any]


class _RunProjectSetupOptions(TypedDict):
    project_id: int
    spec_file_path: str
    hydrate_context: Callable[[str, int], Awaitable[_SetupWorkflowContext]]
    build_tool_context: Callable[[_SetupWorkflowContext], object]
    link_spec_to_product: Callable[..., dict[str, Any]]
    refresh_project_context: Callable[[int, object], object]
    load_project: Callable[[int], object]
    setup_blocker: Callable[[object], str | None]
    run_vision_agent: Callable[..., Awaitable[dict[str, Any]]]
    now_iso: Callable[[], str]
    save_session_state: Callable[[str, dict[str, Any]], None]


def _set_setup_failure_meta(
    state: dict[str, Any],
    source: dict[str, Any] | None,
    *,
    error_message: str | None,
) -> dict[str, Any]:
    metadata = workflow_state.failure_meta(
        source,
        fallback_summary=error_message,
    )
    state["setup_failure_artifact_id"] = metadata["failure_artifact_id"]
    state["setup_failure_stage"] = metadata["failure_stage"]
    state["setup_failure_summary"] = metadata["failure_summary"]
    state["setup_raw_output_preview"] = metadata["raw_output_preview"]
    state["setup_has_full_artifact"] = metadata["has_full_artifact"]
    return metadata


def _clear_setup_failure_meta(state: dict[str, Any]) -> None:
    state["setup_failure_artifact_id"] = None
    state["setup_failure_stage"] = None
    state["setup_failure_summary"] = None
    state["setup_raw_output_preview"] = None
    state["setup_has_full_artifact"] = False


async def run_project_setup(
    *,
    session_id: str,
    **options: Unpack[_RunProjectSetupOptions],
) -> dict[str, Any]:
    """Run spec-link setup, update session state, and optionally auto-run vision."""
    context = await options["hydrate_context"](
        session_id,
        options["project_id"],
    )
    tool_context = options["build_tool_context"](context)

    result = options["link_spec_to_product"](
        {
            "product_id": options["project_id"],
            "spec_path": options["spec_file_path"],
        },
        tool_context=tool_context,
    )

    # Rehydrate active project + compiled authority cache after setup attempt.
    options["refresh_project_context"](options["project_id"], tool_context)

    setup_passed = bool(result.get("success") and result.get("compile_success"))
    error_message = None
    next_state = OrchestratorState.SETUP_REQUIRED.value
    vision_auto_run: dict[str, Any] = {
        "attempted": False,
        "success": False,
        "is_complete": None,
        "error": None,
        "trigger": "auto_setup_transition",
        **workflow_state.failure_meta(None),
    }

    if not setup_passed:
        error_message = (
            result.get("compile_error") or result.get("error") or "Setup failed"
        )
    else:
        latest_product = options["load_project"](options["project_id"])
        blocker = options["setup_blocker"](latest_product)
        if blocker:
            setup_passed = False
            error_message = blocker
        else:
            vision_result = await options["run_vision_agent"](
                context.state,
                project_id=options["project_id"],
                user_input="",
            )
            attempt_is_complete = (
                bool(vision_result.get("is_complete"))
                if vision_result.get("success")
                else False
            )
            record_vision_attempt(
                context.state,
                trigger="auto_setup_transition",
                input_context=vision_result.get("input_context") or {},
                output_artifact=vision_result.get("output_artifact") or {},
                is_complete=attempt_is_complete,
                failure_meta=vision_result,
                now_iso=options["now_iso"],
            )
            next_state = set_vision_fsm_state(
                context.state,
                is_complete=attempt_is_complete,
                now_iso=options["now_iso"],
            )
            vision_auto_run = {
                "attempted": True,
                "success": bool(vision_result.get("success")),
                "is_complete": vision_result.get("is_complete")
                if vision_result.get("success")
                else None,
                "error": vision_result.get("error"),
                "trigger": "auto_setup_transition",
                **workflow_state.failure_meta(
                    vision_result,
                    fallback_summary=vision_result.get("error"),
                ),
            }

    if not setup_passed:
        context.state["fsm_state"] = OrchestratorState.SETUP_REQUIRED.value
        context.state["fsm_state_entered_at"] = options["now_iso"]()
        next_state = OrchestratorState.SETUP_REQUIRED.value
        setup_failure_meta = _set_setup_failure_meta(
            context.state,
            result,
            error_message=error_message,
        )
    else:
        _clear_setup_failure_meta(context.state)
        setup_failure_meta = workflow_state.failure_meta(None)

    context.state["setup_status"] = "passed" if setup_passed else "failed"
    context.state["setup_error"] = error_message
    context.state["setup_spec_file_path"] = options["spec_file_path"]

    options["save_session_state"](session_id, context.state)

    return {
        "passed": setup_passed,
        "error": error_message,
        "detail": result,
        "fsm_state": next_state,
        "vision_auto_run": vision_auto_run,
        **setup_failure_meta,
    }


__all__ = ["run_project_setup"]
