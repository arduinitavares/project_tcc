"""Deterministic context-injection adapters for orchestrated generation tools.

These adapters preserve the original public tool names while removing model
control over context-heavy arguments (technical spec, compiled authority, and
prior states). The Orchestrator LLM passes only user intent fields.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, cast

from google.adk.tools import AgentTool, ToolContext

from orchestrator_agent.agent_tools.backlog_primer.agent import (
    root_agent as backlog_agent,
)
from orchestrator_agent.agent_tools.product_vision_tool.agent import (
    root_agent as vision_agent,
)
from orchestrator_agent.agent_tools.roadmap_builder.agent import (
    root_agent as roadmap_agent,
)
from orchestrator_agent.agent_tools.sprint_planner_tool.agent import (
    root_agent as sprint_planner_agent,
)
from orchestrator_agent.agent_tools.user_story_writer_tool.agent import (
    root_agent as story_writer_agent,
)
from tools.orchestrator_tools import fetch_sprint_candidates


_PRODUCT_VISION_TOOL = AgentTool(agent=vision_agent)
_BACKLOG_PRIMER_TOOL = AgentTool(agent=backlog_agent)
_ROADMAP_BUILDER_TOOL = AgentTool(agent=roadmap_agent)
_SPRINT_PLANNER_TOOL = AgentTool(agent=sprint_planner_agent)
_USER_STORY_WRITER_TOOL = AgentTool(agent=story_writer_agent)


def _state(tool_context: Optional[ToolContext]) -> Dict[str, Any]:
    """Return state dict from ToolContext or empty dict when unavailable."""
    if not tool_context or tool_context.state is None:
        return {}
    return cast(Dict[str, Any], tool_context.state)


def _as_text(value: Any) -> str:
    """Normalize arbitrary values into text for tool arguments."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _json_or_no_history(value: Any) -> str:
    """Serialize stateful prior payloads to JSON or fallback to NO_HISTORY."""
    if value is None:
        return "NO_HISTORY"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "NO_HISTORY"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "NO_HISTORY"


def _missing_context_error(
    *,
    code: str,
    missing_context: Sequence[str],
    guidance: str,
) -> Dict[str, Any]:
    """Build standardized fail-fast payload for orchestration states."""
    missing = list(missing_context)
    return {
        "is_complete": False,
        "error": code,
        "missing_context": missing,
        "clarifying_questions": [
            (
                f"Missing context: {', '.join(missing)}. "
                f"{guidance}"
            )
        ],
        "message": (
            "Deterministic adapter blocked tool execution due to missing "
            "volatile context."
        ),
    }


def _parse_roadmap_payload(value: Any) -> Optional[Dict[str, Any]]:
    """Parse roadmap payload from state into a dict when possible."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return cast(Dict[str, Any], parsed)
    return None


def _extract_roadmap_dict(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Load roadmap from active_project first, then roadmap_result."""
    active_project = state.get("active_project")
    if isinstance(active_project, dict):
        roadmap = _parse_roadmap_payload(active_project.get("roadmap"))
        if roadmap:
            return roadmap
    roadmap_result = _parse_roadmap_payload(state.get("roadmap_result"))
    if roadmap_result:
        return roadmap_result
    return None


def _derive_requirement_context(
    *,
    state: Dict[str, Any],
    parent_requirement: str,
) -> Optional[str]:
    """Derive requirement context from roadmap release metadata."""
    roadmap = _extract_roadmap_dict(state)
    if not roadmap:
        return None

    releases = roadmap.get("roadmap_releases")
    if not isinstance(releases, list):
        return None

    normalized_parent = parent_requirement.strip()
    for release in releases:
        if not isinstance(release, dict):
            continue
        items = release.get("items")
        if not isinstance(items, list):
            continue

        if normalized_parent not in [str(item).strip() for item in items]:
            continue

        theme = _as_text(release.get("theme")).strip()
        focus_area = _as_text(release.get("focus_area")).strip()
        reasoning = _as_text(release.get("reasoning")).strip()
        parts: List[str] = []
        if theme:
            parts.append(f"Theme: {theme}")
        if focus_area:
            parts.append(f"Focus Area: {focus_area}")
        if reasoning:
            parts.append(f"Reasoning: {reasoning}")
        return " | ".join(parts).strip() if parts else None

    return None


def _normalize_velocity(value: Any) -> str:
    """Normalize velocity input to Low/Medium/High."""
    normalized = _as_text(value).strip().lower()
    if normalized == "low":
        return "Low"
    if normalized == "high":
        return "High"
    return "Medium"


def _normalize_duration_days(value: Any) -> int:
    """Normalize sprint duration into schema-safe bounds (1..31)."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 14
    return max(1, min(parsed, 31))


def _normalize_positive_int(value: Any) -> Optional[int]:
    """Normalize optional positive integer fields."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_priority(value: Any, fallback: int) -> int:
    """Ensure priority is always an integer >= 1."""
    parsed = _normalize_positive_int(value)
    return parsed if parsed is not None else max(1, fallback)


def _normalize_selected_story_ids(value: Any) -> List[int]:
    """Normalize selected story IDs while preserving order and uniqueness."""
    if not isinstance(value, list):
        return []
    seen = set()
    normalized: List[int] = []
    for item in value:
        parsed = _normalize_positive_int(item)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    return normalized


def _selection_error(invalid_ids: Sequence[int]) -> Dict[str, Any]:
    """Build deterministic error payload for invalid sprint selections."""
    invalid = list(invalid_ids)
    invalid_text = ", ".join(str(item) for item in invalid)
    return {
        "is_complete": False,
        "error": "SPRINT_SELECTION_INVALID",
        "missing_context": [f"selected_story_ids_not_eligible: {invalid_text}"],
        "clarifying_questions": [
            (
                "Some selected_story_ids are not refined TO_DO candidates: "
                f"{invalid_text}. Please provide eligible story IDs."
            )
        ],
        "message": (
            "Deterministic adapter blocked sprint planning because selection "
            "contains non-eligible stories."
        ),
    }


async def product_vision_tool(
    user_raw_text: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Deterministic adapter for product_vision_tool."""
    if tool_context is None:
        return _missing_context_error(
            code="PRODUCT_VISION_CONTEXT_MISSING",
            missing_context=["tool_context.state"],
            guidance="Retry from orchestrator runtime so session state is available.",
        )

    state = _state(tool_context)
    args = {
        "user_raw_text": user_raw_text,
        "specification_content": _as_text(state.get("pending_spec_content")),
        "compiled_authority": _as_text(state.get("compiled_authority_cached")),
        "prior_vision_state": _json_or_no_history(state.get("vision_components")),
    }
    result = await _PRODUCT_VISION_TOOL.run_async(args=args, tool_context=tool_context)
    return cast(Dict[str, Any], result)


async def backlog_primer_tool(
    user_input: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Deterministic adapter for backlog_primer_tool."""
    if tool_context is None:
        return _missing_context_error(
            code="BACKLOG_CONTEXT_MISSING",
            missing_context=["tool_context.state"],
            guidance="Select a project and ensure specification/authority are loaded.",
        )

    state = _state(tool_context)
    active_project = state.get("active_project")
    vision = ""
    if isinstance(active_project, dict):
        vision = _as_text(active_project.get("vision")).strip()

    technical_spec = _as_text(state.get("pending_spec_content")).strip()
    compiled_authority = _as_text(state.get("compiled_authority_cached")).strip()

    missing: List[str] = []
    if not vision:
        missing.append("active_project.vision")
    if not technical_spec:
        missing.append("pending_spec_content")
    if not compiled_authority:
        missing.append("compiled_authority_cached")

    if missing:
        return _missing_context_error(
            code="BACKLOG_CONTEXT_MISSING",
            missing_context=missing,
            guidance=(
                "Run project selection/spec loading and authority compilation "
                "before backlog generation."
            ),
        )

    args = {
        "product_vision_statement": vision,
        "technical_spec": technical_spec,
        "compiled_authority": compiled_authority,
        "prior_backlog_state": _json_or_no_history(state.get("product_backlog")),
        "user_input": user_input,
    }
    result = await _BACKLOG_PRIMER_TOOL.run_async(args=args, tool_context=tool_context)
    return cast(Dict[str, Any], result)


async def roadmap_builder_tool(
    user_input: str,
    time_increment: str = "Milestone-based",
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Deterministic adapter for roadmap_builder_tool."""
    if tool_context is None:
        return _missing_context_error(
            code="ROADMAP_CONTEXT_MISSING",
            missing_context=["tool_context.state"],
            guidance="Select a project and persist backlog before roadmap generation.",
        )

    state = _state(tool_context)
    active_project = state.get("active_project")
    vision = ""
    if isinstance(active_project, dict):
        vision = _as_text(active_project.get("vision")).strip()

    approved_backlog = state.get("approved_backlog")
    backlog_items: List[Dict[str, Any]] = []
    if isinstance(approved_backlog, dict) and isinstance(
        approved_backlog.get("items"), list
    ):
        backlog_items = cast(List[Dict[str, Any]], approved_backlog["items"])

    technical_spec = _as_text(state.get("pending_spec_content")).strip()
    compiled_authority = _as_text(state.get("compiled_authority_cached")).strip()

    missing: List[str] = []
    if not vision:
        missing.append("active_project.vision")
    if not backlog_items:
        missing.append("approved_backlog.items")
    if not technical_spec:
        missing.append("pending_spec_content")
    if not compiled_authority:
        missing.append("compiled_authority_cached")

    if missing:
        return _missing_context_error(
            code="ROADMAP_CONTEXT_MISSING",
            missing_context=missing,
            guidance=(
                "Save backlog and ensure spec/authority are available before "
                "roadmap generation."
            ),
        )

    args = {
        "backlog_items": backlog_items,
        "product_vision": vision,
        "technical_spec": technical_spec,
        "compiled_authority": compiled_authority,
        "time_increment": time_increment,
        "prior_roadmap_state": _json_or_no_history(state.get("roadmap_result")),
        "user_input": user_input,
    }
    result = await _ROADMAP_BUILDER_TOOL.run_async(args=args, tool_context=tool_context)
    return cast(Dict[str, Any], result)


async def sprint_planner_tool(
    team_velocity_assumption: str = "Medium",
    sprint_duration_days: int = 14,
    user_context: str = "",
    max_story_points: Optional[int] = None,
    include_task_decomposition: bool = True,
    selected_story_ids: Optional[List[int]] = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Deterministic adapter for sprint_planner_tool."""
    if tool_context is None:
        return _missing_context_error(
            code="SPRINT_CONTEXT_MISSING",
            missing_context=["tool_context.state"],
            guidance="Select a project before sprint planning.",
        )

    state = _state(tool_context)
    active_project = state.get("active_project")
    product_id = None
    if isinstance(active_project, dict):
        product_id = _normalize_positive_int(active_project.get("product_id"))

    if product_id is None:
        return _missing_context_error(
            code="SPRINT_CONTEXT_MISSING",
            missing_context=["active_project.product_id"],
            guidance="Select an active project, then retry sprint planning.",
        )

    candidate_result = fetch_sprint_candidates(product_id=product_id)
    if not candidate_result.get("success"):
        return _missing_context_error(
            code="SPRINT_CANDIDATE_FETCH_FAILED",
            missing_context=["sprint candidates"],
            guidance="Retry fetching the backlog after selecting the active project.",
        )

    candidate_rows = candidate_result.get("stories")
    if not isinstance(candidate_rows, list) or not candidate_rows:
        return _missing_context_error(
            code="SPRINT_CANDIDATES_MISSING",
            missing_context=["refined TO_DO stories"],
            guidance="Only refined stories are sprint-eligible. Refine stories first.",
        )

    selected_ids = _normalize_selected_story_ids(selected_story_ids)
    selected_rows = candidate_rows
    if selected_ids:
        by_id: Dict[int, Dict[str, Any]] = {}
        for row in candidate_rows:
            if isinstance(row, dict):
                story_id = _normalize_positive_int(row.get("story_id"))
                if story_id is not None:
                    by_id[story_id] = row
        invalid_ids = [story_id for story_id in selected_ids if story_id not in by_id]
        if invalid_ids:
            return _selection_error(invalid_ids)
        selected_rows = [by_id[story_id] for story_id in selected_ids]

    available_stories: List[Dict[str, Any]] = []
    for idx, row in enumerate(selected_rows, start=1):
        if not isinstance(row, dict):
            continue
        story_id = _normalize_positive_int(row.get("story_id"))
        if story_id is None:
            continue
        story_title = _as_text(row.get("story_title") or row.get("title")).strip()
        if not story_title:
            story_title = f"Story {story_id}"

        available_stories.append(
            {
                "story_id": story_id,
                "story_title": story_title,
                "priority": _coerce_priority(row.get("priority"), idx),
                "story_points": _normalize_positive_int(row.get("story_points")),
            }
        )

    if not available_stories:
        return _missing_context_error(
            code="SPRINT_CANDIDATES_MISSING",
            missing_context=["sprint-eligible stories with valid IDs"],
            guidance="Refine stories first, then retry sprint planning.",
        )

    args = {
        "available_stories": available_stories,
        "team_velocity_assumption": _normalize_velocity(team_velocity_assumption),
        "sprint_duration_days": _normalize_duration_days(sprint_duration_days),
        "user_context": _as_text(user_context).strip() or None,
        "max_story_points": _normalize_positive_int(max_story_points),
        "include_task_decomposition": bool(include_task_decomposition),
    }

    result = await _SPRINT_PLANNER_TOOL.run_async(args=args, tool_context=tool_context)
    return cast(Dict[str, Any], result)


async def user_story_writer_tool(
    parent_requirement: str,
    requirement_context: str = "",
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Deterministic adapter for user_story_writer_tool."""
    if tool_context is None:
        return _missing_context_error(
            code="STORY_CONTEXT_MISSING",
            missing_context=["tool_context.state"],
            guidance="Select a project and ensure roadmap/spec/authority are present.",
        )

    state = _state(tool_context)
    technical_spec = _as_text(state.get("pending_spec_content")).strip()
    compiled_authority = _as_text(state.get("compiled_authority_cached")).strip()

    derived_context = _derive_requirement_context(
        state=state, parent_requirement=parent_requirement
    )
    resolved_requirement_context = derived_context or requirement_context.strip()

    missing: List[str] = []
    if not technical_spec:
        missing.append("pending_spec_content")
    if not compiled_authority:
        missing.append("compiled_authority_cached")
    if not resolved_requirement_context:
        missing.append("roadmap release metadata (or explicit requirement_context)")

    if missing:
        return _missing_context_error(
            code="STORY_CONTEXT_MISSING",
            missing_context=missing,
            guidance=(
                "Save roadmap first so release metadata can be used to decompose "
                "requirements into stories."
            ),
        )

    args = {
        "parent_requirement": parent_requirement,
        "requirement_context": resolved_requirement_context,
        "technical_spec": technical_spec,
        "compiled_authority": compiled_authority,
    }
    result = await _USER_STORY_WRITER_TOOL.run_async(
        args=args, tool_context=tool_context
    )
    return cast(Dict[str, Any], result)


__all__ = [
    "product_vision_tool",
    "backlog_primer_tool",
    "roadmap_builder_tool",
    "sprint_planner_tool",
    "user_story_writer_tool",
]
