from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
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
PUBLIC_TASK_KIND_VALUES = (
    "analysis",
    "design",
    "implementation",
    "testing",
    "documentation",
    "refactor",
)
_DECOMP_OTHER_TASK_KIND_PATTERN = re.compile(
    r"task '(?P<description>[^']+)': 'task_kind' cannot be 'other'",
)


async def _invoke_sprint_agent(payload: SprintPlannerInput) -> str:
    return await invoke_agent_to_text(
        agent=sprint_agent,
        runner_identity=SPRINT_RUNNER_IDENTITY,
        payload_json=payload.model_dump_json(),
        no_text_error="Sprint agent returned no text response",
    )


def _allowed_task_kind_hint() -> str:
    return ", ".join(PUBLIC_TASK_KIND_VALUES)


def _lookup_path(payload: Any, path: Sequence[Any]) -> Any:
    current = payload
    for segment in path:
        if isinstance(segment, int):
            if not isinstance(current, list) or segment >= len(current):
                return None
            current = current[segment]
            continue
        if not isinstance(segment, str) or not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current


def _task_description_for_loc(
    payload: Optional[Mapping[str, Any]],
    loc: Sequence[Any],
) -> Optional[str]:
    if payload is None or len(loc) < 2 or loc[-1] != "task_kind":
        return None
    parent = _lookup_path(payload, loc[:-1])
    if not isinstance(parent, Mapping):
        return None
    description = parent.get("description")
    if not isinstance(description, str):
        return None
    trimmed = description.strip()
    return trimmed or None


def _task_kind_hint(
    invalid_value: Any,
    *,
    task_description: Optional[str] = None,
) -> Optional[str]:
    if not isinstance(invalid_value, str):
        return None
    trimmed = invalid_value.strip()
    if not trimmed:
        return None
    prefix = (
        f"Task '{task_description}' uses unsupported task_kind '{trimmed}'."
        if task_description
        else f"Unsupported task_kind '{trimmed}'."
    )
    return f"{prefix} Use one of: {_allowed_task_kind_hint()}."


def _public_hint_from_structured_error(
    error: Mapping[str, Any],
    *,
    parsed_output: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    msg = error.get("msg")
    message_hint = msg.strip() if isinstance(msg, str) else None
    loc = error.get("loc")
    if isinstance(loc, (list, tuple)) and loc and loc[-1] == "task_kind":
        hint = _task_kind_hint(
            error.get("input"),
            task_description=_task_description_for_loc(parsed_output, loc),
        )
        if hint:
            return hint

        task_description = _task_description_for_loc(parsed_output, loc)
        if task_description and message_hint:
            return f"Task '{task_description}' has invalid task_kind. {message_hint}"
        if message_hint:
            return message_hint
        if task_description:
            return (
                f"Task '{task_description}' has invalid task_kind. "
                f"Use one of: {_allowed_task_kind_hint()}."
            )
        return f"Task has invalid task_kind. Use one of: {_allowed_task_kind_hint()}."

    return message_hint or None


def _compact_public_validation_errors(
    validation_errors: Sequence[Any] | None,
    *,
    parsed_output: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    hints: List[str] = []
    seen: set[str] = set()
    for error in validation_errors or []:
        hint: Optional[str] = None
        if isinstance(error, Mapping):
            hint = _public_hint_from_structured_error(
                error,
                parsed_output=parsed_output,
            )
        elif isinstance(error, str):
            match = _DECOMP_OTHER_TASK_KIND_PATTERN.search(error)
            if match:
                hint = _task_kind_hint(
                    "other",
                    task_description=match.group("description"),
                )
            else:
                trimmed = error.strip()
                hint = trimmed or None
        if hint and hint not in seen:
            seen.add(hint)
            hints.append(hint)
    return hints


def _failure(
    *,
    project_id: int,
    input_context: Dict[str, Any],
    failure_stage: str,
    message: str,
    raw_text: Optional[str] = None,
    validation_errors: Optional[Sequence[Any]] = None,
    public_validation_errors: Optional[List[str]] = None,
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
        "validation_errors": list(public_validation_errors or []),
        "is_complete": False,
    }
    artifact.update(metadata)

    return {
        "success": False,
        "input_context": input_context,
        "output_artifact": artifact,
        "is_complete": None,
        "error": message,
        "validation_errors": list(public_validation_errors or []),
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
        public_validation_errors = _compact_public_validation_errors(exc.errors())
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="input_validation",
            message=f"Sprint input validation failed: {exc}",
            validation_errors=exc.errors(),
            public_validation_errors=public_validation_errors,
            exception=exc,
        )

    try:
        raw_text = await _invoke_sprint_agent(payload)
    except AgentInvocationError as exc:
        public_validation_errors = _compact_public_validation_errors(exc.validation_errors)
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invocation_exception",
            message=f"Sprint runtime failed: {exc}",
            raw_text=exc.partial_output,
            validation_errors=exc.validation_errors,
            public_validation_errors=public_validation_errors,
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
        public_validation_errors = _compact_public_validation_errors(
            exc.errors(),
            parsed_output=parsed,
        )
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message=f"Sprint output validation failed: {exc}",
            raw_text=raw_text,
            validation_errors=exc.errors(),
            public_validation_errors=public_validation_errors,
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
        structured_errors = [{"msg": error} for error in decomp_errors]
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message="Sprint output validation failed: poor task decomposition quality",
            raw_text=raw_text,
            validation_errors=structured_errors,
            public_validation_errors=_compact_public_validation_errors(decomp_errors),
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
        structured_errors = [{"msg": error} for error in binding_errors]
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message="Sprint output validation failed: invalid task invariant bindings",
            raw_text=raw_text,
            validation_errors=structured_errors,
            public_validation_errors=_compact_public_validation_errors(binding_errors),
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
