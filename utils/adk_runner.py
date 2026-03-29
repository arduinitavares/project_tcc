from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from utils.failure_artifacts import AgentInvocationError


def _iter_exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _extract_validation_errors(exc: BaseException) -> Optional[List[Dict[str, Any]]]:
    for candidate in _iter_exception_chain(exc):
        errors = getattr(candidate, "errors", None)
        if not callable(errors):
            continue
        try:
            raw_errors = errors()
        except TypeError:
            continue
        if isinstance(raw_errors, list):
            return raw_errors
    return None


def extract_final_response_text(events: List[Any]) -> str:
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


def extract_partial_response_text(events: List[Any]) -> str:
    final = extract_final_response_text(events)
    if final:
        return final

    fragments: List[str] = []
    for event in events:
        content = getattr(event, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", "")
            if text:
                fragments.append(text)
    return "\n".join(fragments).strip()


def parse_json_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    candidate = (raw_text or "").strip()
    if not candidate:
        return None

    fenced = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        candidate,
        flags=re.IGNORECASE | re.DOTALL,
    )
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


def get_agent_model_info(agent: Any) -> Dict[str, Any]:
    model = getattr(agent, "model", None)
    return {
        "agent_name": getattr(agent, "name", None),
        "model_class": type(model).__name__ if model is not None else None,
        "model_id": getattr(model, "model", None),
        "extra_body": getattr(model, "extra_body", None),
    }


async def invoke_agent_to_text(
    *,
    agent: Any,
    runner_identity: Any,
    payload_json: str,
    no_text_error: str,
) -> str:
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name=runner_identity.app_name,
        session_service=session_service,
    )
    session = await session_service.create_session(
        app_name=runner_identity.app_name,
        user_id=runner_identity.user_id,
    )

    events: List[Any] = []
    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=payload_json)],
    )

    try:
        async for event in runner.run_async(
            user_id=runner_identity.user_id,
            session_id=session.id,
            new_message=message,
        ):
            events.append(event)
    except Exception as exc:  # pylint: disable=broad-except
        partial_output = extract_partial_response_text(events) or None
        raise AgentInvocationError(
            str(exc),
            partial_output=partial_output,
            event_count=len(events),
            validation_errors=_extract_validation_errors(exc),
        ) from exc

    response_text = extract_final_response_text(events)
    if not response_text:
        raise ValueError(no_text_error)
    return response_text
