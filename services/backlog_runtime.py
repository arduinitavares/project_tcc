from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from orchestrator_agent.agent_tools.backlog_primer.agent import (
    root_agent as backlog_agent,
)
from orchestrator_agent.agent_tools.backlog_primer.schemes import (
    InputSchema,
    OutputSchema,
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _normalize_prior_backlog_state(value: Any) -> str:
    if value is None:
        return "NO_HISTORY"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "NO_HISTORY"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "NO_HISTORY"


def build_backlog_input_context(
    state: Dict[str, Any],
    *,
    user_input: Optional[str],
) -> Dict[str, str]:
    vision_assessment = state.get("product_vision_assessment") or {}
    vision_stmt = vision_assessment.get("product_vision_statement") or ""
    
    return {
        "product_vision_statement": vision_stmt,
        "technical_spec": _as_text(state.get("pending_spec_content")),
        "compiled_authority": _as_text(state.get("compiled_authority_cached")),
        "prior_backlog_state": _normalize_prior_backlog_state(state.get("backlog_items")),
        "user_input": user_input or "",
    }


def _extract_final_response_text(events: List[Any]) -> str:
    for event in reversed(events):
        content = getattr(event, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        text_parts = [getattr(part, "text", "") for part in parts if getattr(part, "text", "")]
        merged = "\n".join(text_parts).strip()
        if merged:
            return merged
    return ""


def _parse_json_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    candidate = (raw_text or "").strip()
    if not candidate:
        return None

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        sliced = candidate[start : end + 1]
        try:
            parsed = json.loads(sliced)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


async def _invoke_backlog_agent(payload: InputSchema) -> str:
    session_service = InMemorySessionService()
    runner = Runner(
        agent=backlog_agent,
        app_name="backlog_primer",
        session_service=session_service,
    )
    session = await session_service.create_session(
        app_name="backlog_primer",
        user_id="dashboard_backlog",
    )

    events: List[Any] = []
    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=payload.model_dump_json())],
    )

    async for event in runner.run_async(
        user_id="dashboard_backlog",
        session_id=session.id,
        new_message=message,
    ):
        events.append(event)

    response_text = _extract_final_response_text(events)
    if not response_text:
        raise ValueError("Backlog agent returned no text response")
    return response_text


def _failure(
    *,
    input_context: Dict[str, Any],
    message: str,
    raw_text: Optional[str] = None,
) -> Dict[str, Any]:
    artifact: Dict[str, Any] = {
        "error": "BACKLOG_GENERATION_FAILED",
        "message": message,
        "is_complete": False,
        "clarifying_questions": [],
    }
    if raw_text:
        artifact["raw_output"] = raw_text[:2000]

    return {
        "success": False,
        "input_context": input_context,
        "output_artifact": artifact,
        "is_complete": None,
        "error": message,
    }


async def run_backlog_agent_from_state(
    state: Dict[str, Any],
    *,
    user_input: Optional[str],
) -> Dict[str, Any]:
    input_context = build_backlog_input_context(state, user_input=user_input)

    try:
        payload = InputSchema.model_validate(input_context)
    except ValidationError as exc:
        return _failure(
            input_context=input_context,
            message=f"Backlog input validation failed: {exc}",
        )

    try:
        raw_text = await _invoke_backlog_agent(payload)
    except Exception as exc:  # pylint: disable=broad-except
        return _failure(
            input_context=input_context,
            message=f"Backlog runtime failed: {exc}",
        )

    parsed = _parse_json_payload(raw_text)
    if parsed is None:
        return _failure(
            input_context=input_context,
            message="Backlog response is not valid JSON",
            raw_text=raw_text,
        )

    try:
        output_model = OutputSchema.model_validate(parsed)
    except ValidationError as exc:
        return _failure(
            input_context=input_context,
            message=f"Backlog output validation failed: {exc}",
            raw_text=raw_text,
        )

    output_artifact = output_model.model_dump(exclude_none=True)
    return {
        "success": True,
        "input_context": input_context,
        "output_artifact": output_artifact,
        "is_complete": bool(output_artifact.get("is_complete", False)),
        "error": None,
    }
