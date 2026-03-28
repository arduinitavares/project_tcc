from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from orchestrator_agent.agent_tools.user_story_writer_tool.agent import (
    root_agent as story_agent,
)
from orchestrator_agent.agent_tools.user_story_writer_tool.schemes import (
    UserStoryWriterInput,
    UserStoryWriterOutput,
)
from services.interview_runtime import hydrate_story_runtime_from_legacy
from utils.adk_runner import get_agent_model_info, invoke_agent_to_text, parse_json_payload
from utils.failure_artifacts import AgentInvocationError, write_failure_artifact
from utils.runtime_config import STORY_RUNNER_IDENTITY

logger = logging.getLogger(__name__)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def build_story_input_context(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
) -> Dict[str, Any]:
    # Extract the context for this specific requirement from the roadmap
    roadmap_releases = state.get("roadmap_releases") or []
    requirement_context = f"Requirement: {parent_requirement}"
    
    for release in roadmap_releases:
        if parent_requirement in release.get("items", []):
            theme = release.get("theme", "No theme specified")
            reasoning = release.get("reasoning", "No reasoning specified")
            focus = release.get("focus_area", "No focus area specified")
            requirement_context = (
                f"Part of Release: {release.get('release_name', 'Unknown')}\n"
                f"Theme: {theme}\n"
                f"Focus Area: {focus}\n"
                f"Strategic Reasoning: {reasoning}"
            )
            break

    global_roadmap_context = "Global Roadmap Constraints (Do not overlap with sibling requirements):\n"
    for r_idx, release in enumerate(roadmap_releases):
        global_roadmap_context += f"Milestone {r_idx + 1}: {release.get('release_name', 'Unnamed')}\n"
        for item in release.get("items", []):
            global_roadmap_context += f"  - {item}\n"

    already_generated = "Already Generated Stories (Do not duplicate these):\n"
    artifact_registry: Dict[str, str] = {}
    story_outputs = state.get("story_outputs", {})
    added_any_stories = False
    for req_name, artifact in story_outputs.items():
        if req_name == parent_requirement:
            continue
        if isinstance(artifact, dict):
            stories = artifact.get("user_stories", [])
            if stories:
                added_any_stories = True
                already_generated += f"\nRequirement: '{req_name}' contains:\n"
                for story in stories:
                    already_generated += f"  - {story.get('story_title', 'Untitled')}: {story.get('statement', '')}\n"
                    
                    # Build artifact registry
                    produced_artifacts = story.get("produced_artifacts", [])
                    for pa in produced_artifacts:
                        if isinstance(pa, str) and pa.strip():
                            artifact_registry[pa.strip()] = req_name

    if not added_any_stories:
        already_generated = "No stories generated yet for other requirements."

    return {
        "parent_requirement": parent_requirement,
        "requirement_context": requirement_context,
        "technical_spec": _as_text(state.get("pending_spec_content")),
        "compiled_authority": _as_text(state.get("compiled_authority_cached")),
        "global_roadmap_context": global_roadmap_context.strip(),
        "already_generated_milestone_stories": already_generated.strip(),
        "artifact_registry": artifact_registry,
    }


async def _invoke_story_agent(payload: UserStoryWriterInput) -> str:
    return await invoke_agent_to_text(
        agent=story_agent,
        runner_identity=STORY_RUNNER_IDENTITY,
        payload_json=payload.model_dump_json(),
        no_text_error="Story agent returned no text response",
    )


def _failure(
    *,
    project_id: int,
    parent_requirement: str,
    input_context: Dict[str, Any],
    failure_stage: str,
    message: str,
    raw_text: Optional[str] = None,
    validation_errors: Optional[List[Dict[str, Any]]] = None,
    exception: Optional[BaseException] = None,
) -> Dict[str, Any]:
    artifact_result = write_failure_artifact(
        phase="story",
        project_id=project_id,
        failure_stage=failure_stage,
        failure_summary=message,
        raw_output=raw_text,
        context={
            "parent_requirement": parent_requirement,
            "input_context": input_context,
        },
        model_info={
            **get_agent_model_info(story_agent),
            "app_name": STORY_RUNNER_IDENTITY.app_name,
            "user_id": STORY_RUNNER_IDENTITY.user_id,
        },
        validation_errors=validation_errors,
        exception=exception,
    )
    metadata = artifact_result["metadata"]

    if exception is not None:
        logger.exception(
            "Story generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )
    else:
        logger.error(
            "Story generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )

    artifact: Dict[str, Any] = {
        "error": "STORY_GENERATION_FAILED",
        "message": message,
        "is_complete": False,
        "clarifying_questions": [],
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


def _with_failure_metadata(
    result: Dict[str, Any],
    *,
    classification: str,
    draft_kind: Optional[str],
    is_reusable: bool,
    request_payload: Dict[str, Any],
) -> Dict[str, Any]:
    result.update(
        {
            "classification": classification,
            "draft_kind": draft_kind,
            "is_reusable": is_reusable,
            "request_payload": request_payload,
        }
    )
    return result


def _get_latest_reusable_story_artifact(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
) -> Optional[Dict[str, Any]]:
    runtime = hydrate_story_runtime_from_legacy(
        state,
        parent_requirement=parent_requirement,
    )
    draft_projection = runtime.get("draft_projection") or {}
    attempt_id = draft_projection.get("latest_reusable_attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        return None

    for attempt in reversed(runtime.get("attempt_history") or []):
        if not isinstance(attempt, dict):
            continue
        if attempt.get("attempt_id") != attempt_id:
            continue
        artifact = attempt.get("output_artifact")
        return artifact if isinstance(artifact, dict) else None
    return None


def _collect_unabsorbed_feedback_text(runtime: Dict[str, Any]) -> List[str]:
    feedback_projection = runtime.get("feedback_projection") or {}
    if not isinstance(feedback_projection, dict):
        return []

    items = feedback_projection.get("items") or []
    if not isinstance(items, list):
        return []

    feedback_text: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "unabsorbed":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            feedback_text.append(text)
    return feedback_text


def build_story_request_payload(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
    current_user_input: Optional[str] = None,
) -> Dict[str, Any]:
    input_context = build_story_input_context(state, parent_requirement=parent_requirement)
    runtime = hydrate_story_runtime_from_legacy(
        state,
        parent_requirement=parent_requirement,
    )

    reusable_artifact = _get_latest_reusable_story_artifact(
        state,
        parent_requirement=parent_requirement,
    )
    if reusable_artifact:
        input_context["requirement_context"] += (
            "\n\n--- PREVIOUS DRAFT TO REFINE ---\n"
            f"{json.dumps(reusable_artifact, indent=2)}"
        )

    feedback_items = _collect_unabsorbed_feedback_text(runtime)
    if isinstance(current_user_input, str) and current_user_input.strip():
        feedback_items.append(current_user_input)
    if feedback_items:
        input_context["requirement_context"] += (
            "\n\n--- USER REFINEMENT FEEDBACK ---\n"
            + "\n".join(feedback_items)
        )

    return input_context


async def run_story_agent_request(
    request_payload: Dict[str, Any],
    *,
    project_id: int,
    parent_requirement: str,
) -> Dict[str, Any]:
    try:
        payload = UserStoryWriterInput.model_validate(request_payload)
    except ValidationError as exc:
        return _with_failure_metadata(
            _failure(
                project_id=project_id,
                parent_requirement=parent_requirement,
                input_context=request_payload,
                failure_stage="input_validation",
                message=f"Story input validation failed: {exc}",
                validation_errors=exc.errors(),
                exception=exc,
            ),
            classification="nonreusable_schema_failure",
            draft_kind=None,
            is_reusable=False,
            request_payload=request_payload,
        )

    try:
        raw_text = await _invoke_story_agent(payload)
    except AgentInvocationError as exc:
        return _with_failure_metadata(
            _failure(
                project_id=project_id,
                parent_requirement=parent_requirement,
                input_context=request_payload,
                failure_stage="invocation_exception",
                message=f"Story runtime failed: {exc}",
                raw_text=exc.partial_output,
                exception=exc,
            ),
            classification="nonreusable_provider_failure",
            draft_kind=None,
            is_reusable=False,
            request_payload=request_payload,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _with_failure_metadata(
            _failure(
                project_id=project_id,
                parent_requirement=parent_requirement,
                input_context=request_payload,
                failure_stage="invocation_exception",
                message=f"Story runtime failed: {exc}",
                exception=exc,
            ),
            classification="nonreusable_provider_failure",
            draft_kind=None,
            is_reusable=False,
            request_payload=request_payload,
        )

    parsed = parse_json_payload(raw_text)
    if parsed is None:
        return _with_failure_metadata(
            _failure(
                project_id=project_id,
                parent_requirement=parent_requirement,
                input_context=request_payload,
                failure_stage="invalid_json",
                message="Story response is not valid JSON",
                raw_text=raw_text,
            ),
            classification="nonreusable_schema_failure",
            draft_kind=None,
            is_reusable=False,
            request_payload=request_payload,
        )

    try:
        output_model = UserStoryWriterOutput.model_validate(parsed)
    except ValidationError as exc:
        return _with_failure_metadata(
            _failure(
                project_id=project_id,
                parent_requirement=parent_requirement,
                input_context=request_payload,
                failure_stage="output_validation",
                message=f"Story output validation failed: {exc}",
                raw_text=raw_text,
                validation_errors=exc.errors(),
                exception=exc,
            ),
            classification="nonreusable_schema_failure",
            draft_kind=None,
            is_reusable=False,
            request_payload=request_payload,
        )

    output_artifact = output_model.model_dump(exclude_none=True)
    return {
        "success": True,
        "input_context": request_payload,
        "output_artifact": output_artifact,
        "classification": "reusable_content_result",
        "draft_kind": (
            "complete_draft"
            if bool(output_artifact.get("is_complete", False))
            else "incomplete_draft"
        ),
        "is_reusable": True,
        "is_complete": bool(output_artifact.get("is_complete", False)),
        "request_payload": request_payload,
        "error": None,
        "failure_artifact_id": None,
        "failure_stage": None,
        "failure_summary": None,
        "raw_output_preview": None,
        "has_full_artifact": False,
    }


async def run_story_agent_from_state(
    state: Dict[str, Any],
    *,
    project_id: int,
    parent_requirement: str,
    user_input: Optional[str],
) -> Dict[str, Any]:
    request_payload = build_story_request_payload(
        state,
        parent_requirement=parent_requirement,
        current_user_input=user_input,
    )
    return await run_story_agent_request(
        request_payload,
        project_id=project_id,
        parent_requirement=parent_requirement,
    )
