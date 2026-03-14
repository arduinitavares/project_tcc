from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from orchestrator_agent.agent_tools.product_vision_tool.agent import (
    root_agent as vision_agent,
)
from orchestrator_agent.agent_tools.product_vision_tool.schemes import (
    InputSchema,
    OutputSchema,
)
from utils.adk_runner import get_agent_model_info, invoke_agent_to_text, parse_json_payload
from utils.failure_artifacts import AgentInvocationError, write_failure_artifact
from utils.runtime_config import VISION_RUNNER_IDENTITY

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


def _normalize_prior_vision_state(value: Any) -> str:
    if value is None:
        return "NO_HISTORY"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "NO_HISTORY"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "NO_HISTORY"


def build_vision_input_context(
    state: Dict[str, Any],
    *,
    user_input: Optional[str],
) -> Dict[str, str]:
    return {
        "user_raw_text": user_input or "",
        "prior_vision_state": _normalize_prior_vision_state(
            state.get("vision_components")
        ),
        "specification_content": _as_text(state.get("pending_spec_content")),
        "compiled_authority": _as_text(state.get("compiled_authority_cached")),
    }

async def _invoke_vision_agent(payload: InputSchema) -> str:
    return await invoke_agent_to_text(
        agent=vision_agent,
        runner_identity=VISION_RUNNER_IDENTITY,
        payload_json=payload.model_dump_json(),
        no_text_error="Vision agent returned no text response",
    )


def _failure(
    *,
    project_id: int,
    input_context: Dict[str, str],
    failure_stage: str,
    message: str,
    raw_text: Optional[str] = None,
    validation_errors: Optional[List[Dict[str, Any]]] = None,
    exception: Optional[BaseException] = None,
) -> Dict[str, Any]:
    artifact_result = write_failure_artifact(
        phase="vision",
        project_id=project_id,
        failure_stage=failure_stage,
        failure_summary=message,
        raw_output=raw_text,
        context={"input_context": input_context},
        model_info={
            **get_agent_model_info(vision_agent),
            "app_name": VISION_RUNNER_IDENTITY.app_name,
            "user_id": VISION_RUNNER_IDENTITY.user_id,
        },
        validation_errors=validation_errors,
        exception=exception,
    )
    metadata = artifact_result["metadata"]
    if exception is not None:
        logger.exception(
            "Vision generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )
    else:
        logger.error(
            "Vision generation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            message,
        )

    artifact: Dict[str, Any] = {
        "error": "VISION_GENERATION_FAILED",
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


async def run_vision_agent_from_state(
    state: Dict[str, Any],
    *,
    project_id: int,
    user_input: Optional[str],
) -> Dict[str, Any]:
    input_context = build_vision_input_context(state, user_input=user_input)

    try:
        payload = InputSchema.model_validate(input_context)
    except ValidationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="input_validation",
            message=f"Vision input validation failed: {exc}",
            validation_errors=exc.errors(),
            exception=exc,
        )

    try:
        raw_text = await _invoke_vision_agent(payload)
    except AgentInvocationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invocation_exception",
            message=f"Vision runtime failed: {exc}",
            raw_text=exc.partial_output,
            exception=exc,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invocation_exception",
            message=f"Vision runtime failed: {exc}",
            exception=exc,
        )

    parsed = parse_json_payload(raw_text)
    if parsed is None:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="invalid_json",
            message="Vision response is not valid JSON",
            raw_text=raw_text,
        )

    try:
        output_model = OutputSchema.model_validate(parsed)
    except ValidationError as exc:
        return _failure(
            project_id=project_id,
            input_context=input_context,
            failure_stage="output_validation",
            message=f"Vision output validation failed: {exc}",
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
