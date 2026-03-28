from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, cast

from pydantic import ValidationError

from orchestrator_agent.agent_tools.sprint_planner_tool.agent import (
    root_agent as sprint_agent,
)
from orchestrator_agent.agent_tools.sprint_planner_tool.schemes import (
    SprintPlannerInput,
    SprintPlannerOutput,
    validate_task_decomposition_quality,
    validate_task_invariant_bindings,
)
from services.sprint_input import prepare_sprint_input_context
from utils.adk_runner import get_agent_model_info, invoke_agent_to_text, parse_json_payload
from utils.failure_artifacts import AgentInvocationError, write_failure_artifact
from utils.runtime_config import SPRINT_RUNNER_IDENTITY

logger = logging.getLogger(__name__)


async def _invoke_sprint_agent(payload: SprintPlannerInput) -> str:
    return await invoke_agent_to_text(
        agent=sprint_agent,
        runner_identity=SPRINT_RUNNER_IDENTITY,
        payload_json=payload.model_dump_json(),
        no_text_error="Sprint agent returned no text response",
    )


def _failure(
    *,
    project_id: int,
    input_context: Dict[str, Any],
    failure_stage: str,
    message: str,
    raw_text: Optional[str] = None,
    validation_errors: Optional[List[Dict[str, Any]]] = None,
    exception: Optional[BaseException] = None,
) -> Dict[str, Any]:
    artifact_result = write_failure_artifact(
        phase="sprint",
        project_id=project_id,
        failure_stage=failure_stage,
        failure_summary=message,
        raw_output=raw_text,
        context={
            "input_context": input_context,
        },
        model_info={
            **get_agent_model_info(sprint_agent),
            "app_name": SPRINT_RUNNER_IDENTITY.app_name,
            "user_id": SPRINT_RUNNER_IDENTITY.user_id,
        },
        validation_errors=validation_errors,
        exception=exception,
    )
    metadata = artifact_result["metadata"]

    if exception is not None:
        logger.exception(
            "Sprint generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )
    else:
        logger.error(
            "Sprint generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )

    artifact: Dict[str, Any] = {
        "error": "SPRINT_GENERATION_FAILED",
        "message": message,
        "is_complete": False,
    }
    artifact.update(metadata)

    return {
        "success": False,
        "input_context": input_context,
        "output_artifact": artifact,
        "is_complete": None,
        "error": message,
        **metadata,
    }


async def run_sprint_agent_from_state(
    state: Dict[str, Any],
    *,
    project_id: int,
    team_velocity_assumption: str,
    sprint_duration_days: int,
    max_story_points: Optional[int],
    include_task_decomposition: bool,
    selected_story_ids: Optional[List[int]] = None,
    user_input: Optional[str] = None,
) -> Dict[str, Any]:
    _ = state
    prepared = prepare_sprint_input_context(
        product_id=project_id,
        team_velocity_assumption=team_velocity_assumption,
        sprint_duration_days=sprint_duration_days,
        user_context=user_input,
        max_story_points=max_story_points,
        include_task_decomposition=include_task_decomposition,
        selected_story_ids=selected_story_ids,
    )
    input_context = cast(Dict[str, Any], prepared.get("input_context") or {})

    if not prepared.get("success"):
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="input_validation",
            message=str(prepared.get("message") or "Sprint input preparation failed."),
        )

    try:
        payload = SprintPlannerInput.model_validate(input_context)
    except ValidationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="input_validation",
            message=f"Sprint input validation failed: {exc}",
            validation_errors=exc.errors(),
            exception=exc,
        )

    try:
        raw_text = await _invoke_sprint_agent(payload)
    except AgentInvocationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invocation_exception",
            message=f"Sprint runtime failed: {exc}",
            raw_text=exc.partial_output,
            exception=exc,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invocation_exception",
            message=f"Sprint runtime failed: {exc}",
            exception=exc,
        )

    parsed = parse_json_payload(raw_text)
    if parsed is None:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invalid_json",
            message="Sprint response is not valid JSON",
            raw_text=raw_text,
        )

    try:
        output_model = SprintPlannerOutput.model_validate(parsed)
    except ValidationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message=f"Sprint output validation failed: {exc}",
            raw_text=raw_text,
            validation_errors=exc.errors(),
            exception=exc,
        )

    has_acceptance_criteria_by_story = {
        story.story_id: bool(story.acceptance_criteria_items)
        for story in payload.available_stories
    }
    acceptance_criteria_items_by_story = {
        story.story_id: list(story.acceptance_criteria_items or [])
        for story in payload.available_stories
    }
    decomp_errors = validate_task_decomposition_quality(
        output_model,
        include_task_decomposition=include_task_decomposition,
        has_acceptance_criteria_by_story=has_acceptance_criteria_by_story,
        acceptance_criteria_items_by_story=acceptance_criteria_items_by_story,
    )
    if decomp_errors:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message="Sprint output validation failed: poor task decomposition quality",
            raw_text=raw_text,
            validation_errors=[{"msg": error} for error in decomp_errors],
        )

    allowed_invariant_ids_by_story = {
        int(story.story_id): list(story.evaluated_invariant_ids or [])
        for story in payload.available_stories
    }
    binding_errors = validate_task_invariant_bindings(
        output_model,
        allowed_invariant_ids_by_story=allowed_invariant_ids_by_story,
    )
    if binding_errors:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message="Sprint output validation failed: invalid task invariant bindings",
            raw_text=raw_text,
            validation_errors=[{"msg": error} for error in binding_errors],
        )

    output_artifact = output_model.model_dump(exclude_none=True)
    output_artifact["is_complete"] = True
    return {
        "success": True,
        "input_context": input_context,
        "output_artifact": output_artifact,
        "is_complete": True,
        "error": None,
        "failure_artifact_id": None,
        "failure_stage": None,
        "failure_summary": None,
        "raw_output_preview": None,
        "has_full_artifact": False,
    }
