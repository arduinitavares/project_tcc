from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from orchestrator_agent.agent_tools.sprint_planner_tool.agent import (
    root_agent as sprint_agent,
)
from orchestrator_agent.agent_tools.sprint_planner_tool.schemes import (
    SprintPlannerInput,
    SprintPlannerOutput,
)
from utils.adk_runner import get_agent_model_info, invoke_agent_to_text, parse_json_payload
from utils.failure_artifacts import AgentInvocationError, write_failure_artifact
from utils.runtime_config import SPRINT_RUNNER_IDENTITY

logger = logging.getLogger(__name__)


def build_sprint_input_context(
    state: Dict[str, Any],
    *,
    team_velocity_assumption: int,
    sprint_duration_days: int,
    max_story_points: int,
    include_task_decomposition: bool,
) -> Dict[str, Any]:
    # Extract available stories from the state
    available_stories = []
    story_outputs = state.get("story_outputs", {})
    for req_name, artifact in story_outputs.items():
        if isinstance(artifact, dict):
            stories = artifact.get("user_stories", [])
            for story in stories:
                # We could add an ID here, but let's just use the title as a unique identifier for now
                # In a real app we would ensure uniqueness or pull from the DB.
                # Here we just pass the dict structure forward to the agent.
                available_stories.append({
                    "title": story.get("story_title", "Untitled"),
                    "statement": story.get("statement", ""),
                    "acceptance_criteria": story.get("acceptance_criteria", []),
                    "story_points": story.get("story_points", 0),
                    "parent_requirement": req_name,
                })

    return {
        "available_stories": available_stories,
        "team_velocity_assumption": team_velocity_assumption,
        "sprint_duration_days": sprint_duration_days,
        "max_story_points": max_story_points,
        "include_task_decomposition": include_task_decomposition,
    }


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
    team_velocity_assumption: int,
    sprint_duration_days: int,
    max_story_points: int,
    include_task_decomposition: bool,
    user_input: Optional[str] = None,
) -> Dict[str, Any]:
    input_context = build_sprint_input_context(
        state,
        team_velocity_assumption=team_velocity_assumption,
        sprint_duration_days=sprint_duration_days,
        max_story_points=max_story_points,
        include_task_decomposition=include_task_decomposition,
    )

    if user_input:
        input_context["user_feedback"] = user_input

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

    output_artifact = output_model.model_dump(exclude_none=True)
    return {
        "success": True,
        "input_context": input_context,
        "output_artifact": output_artifact,
        "is_complete": True,  # Assuming one-shot for sprint generation currently
        "error": None,
        "failure_artifact_id": None,
        "failure_stage": None,
        "failure_summary": None,
        "raw_output_preview": None,
        "has_full_artifact": False,
    }
