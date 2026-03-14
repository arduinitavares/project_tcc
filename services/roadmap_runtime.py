from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from orchestrator_agent.agent_tools.roadmap_builder.agent import (
    root_agent as roadmap_agent,
)
from orchestrator_agent.agent_tools.roadmap_builder.schemes import (
    RoadmapBuilderInput,
    RoadmapBuilderOutput,
)
from utils.adk_runner import get_agent_model_info, invoke_agent_to_text, parse_json_payload
from utils.failure_artifacts import AgentInvocationError, write_failure_artifact
from utils.runtime_config import ROADMAP_RUNNER_IDENTITY

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


def _normalize_prior_roadmap_state(value: Any) -> str:
    if value is None:
        return "NO_HISTORY"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "NO_HISTORY"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "NO_HISTORY"


def build_roadmap_input_context(
    state: Dict[str, Any],
    *,
    user_input: Optional[str],
) -> Dict[str, Any]:
    vision_assessment = state.get("product_vision_assessment") or {}
    vision_stmt = vision_assessment.get("product_vision_statement") or ""
    
    # backlog_items comes from session state (populated after Backlog phase completed)
    backlog_items = state.get("backlog_items") or []

    return {
        "backlog_items": backlog_items,
        "product_vision": vision_stmt,
        "technical_spec": _as_text(state.get("pending_spec_content")),
        "compiled_authority": _as_text(state.get("compiled_authority_cached")),
        "time_increment": "Milestone-based",
        "prior_roadmap_state": _normalize_prior_roadmap_state(state.get("roadmap_releases")),
        "user_input": user_input or "",
    }

async def _invoke_roadmap_agent(payload: RoadmapBuilderInput) -> str:
    return await invoke_agent_to_text(
        agent=roadmap_agent,
        runner_identity=ROADMAP_RUNNER_IDENTITY,
        payload_json=payload.model_dump_json(),
        no_text_error="Roadmap agent returned no text response",
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
        phase="roadmap",
        project_id=project_id,
        failure_stage=failure_stage,
        failure_summary=message,
        raw_output=raw_text,
        context={"input_context": input_context},
        model_info={
            **get_agent_model_info(roadmap_agent),
            "app_name": ROADMAP_RUNNER_IDENTITY.app_name,
            "user_id": ROADMAP_RUNNER_IDENTITY.user_id,
        },
        validation_errors=validation_errors,
        exception=exception,
    )
    metadata = artifact_result["metadata"]
    if exception is not None:
        logger.exception(
            "Roadmap generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )
    else:
        logger.error(
            "Roadmap generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )

    artifact: Dict[str, Any] = {
        "error": "ROADMAP_GENERATION_FAILED",
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


async def run_roadmap_agent_from_state(
    state: Dict[str, Any],
    *,
    project_id: int,
    user_input: Optional[str],
) -> Dict[str, Any]:
    input_context = build_roadmap_input_context(state, user_input=user_input)

    try:
        payload = RoadmapBuilderInput.model_validate(input_context)
    except ValidationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="input_validation",
            message=f"Roadmap input validation failed: {exc}",
            validation_errors=exc.errors(),
            exception=exc,
        )

    try:
        raw_text = await _invoke_roadmap_agent(payload)
    except AgentInvocationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invocation_exception",
            message=f"Roadmap runtime failed: {exc}",
            raw_text=exc.partial_output,
            exception=exc,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invocation_exception",
            message=f"Roadmap runtime failed: {exc}",
            exception=exc,
        )

    parsed = parse_json_payload(raw_text)
    if parsed is None:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invalid_json",
            message="Roadmap response is not valid JSON",
            raw_text=raw_text,
        )

    try:
        output_model = RoadmapBuilderOutput.model_validate(parsed)
    except ValidationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message=f"Roadmap output validation failed: {exc}",
            raw_text=raw_text,
            validation_errors=exc.errors(),
            exception=exc,
        )

    output_artifact = output_model.model_dump(exclude_none=True)
    return {
        "success": True,
        "input_context": input_context,
        "output_artifact": output_artifact,
        "is_complete": bool(output_artifact.get("is_complete", False)),
        "error": None,
        "failure_artifact_id": None,
        "failure_stage": None,
        "failure_summary": None,
        "raw_output_preview": None,
        "has_full_artifact": False,
    }
