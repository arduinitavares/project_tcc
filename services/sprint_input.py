from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from tools.orchestrator_tools import fetch_sprint_candidates


def as_text(value: Any) -> str:
    """Normalize arbitrary values into text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def normalize_velocity(value: Any) -> str:
    """Normalize velocity input to Low/Medium/High."""
    normalized = as_text(value).strip().lower()
    if normalized == "low":
        return "Low"
    if normalized == "high":
        return "High"
    return "Medium"


def normalize_duration_days(value: Any) -> int:
    """Clamp sprint duration to schema-safe bounds."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 14
    return max(1, min(parsed, 31))


def normalize_positive_int(value: Any) -> Optional[int]:
    """Normalize optional positive integer fields."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def coerce_priority(value: Any, fallback: int) -> int:
    """Ensure priority is always an integer >= 1."""
    parsed = normalize_positive_int(value)
    return parsed if parsed is not None else max(1, fallback)


def normalize_selected_story_ids(value: Any) -> List[int]:
    """Normalize selected story IDs while preserving order and uniqueness."""
    if not isinstance(value, list):
        return []
    seen = set()
    normalized: List[int] = []
    for item in value:
        parsed = normalize_positive_int(item)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    return normalized


def velocity_story_limit(velocity: Any) -> int:
    """Upper bound for the story-count heuristic used in the UI."""
    normalized = normalize_velocity(velocity)
    if normalized == "Low":
        return 3
    if normalized == "High":
        return 7
    return 5


def load_sprint_candidates(
    product_id: int,
    *,
    fetch_candidates: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Load and normalize sprint-eligible candidate stories from the database."""
    resolver = fetch_candidates or fetch_sprint_candidates
    raw_result = resolver(product_id=product_id)
    if not raw_result.get("success"):
        return {
            "success": False,
            "error_code": "SPRINT_CANDIDATE_FETCH_FAILED",
            "message": raw_result.get("error") or "Failed to fetch sprint candidates.",
            "stories": [],
        }

    raw_stories = raw_result.get("stories")
    if not isinstance(raw_stories, list):
        raw_stories = []

    stories: List[Dict[str, Any]] = []
    for idx, row in enumerate(raw_stories, start=1):
        if not isinstance(row, dict):
            continue
        story_id = normalize_positive_int(row.get("story_id"))
        if story_id is None:
            continue

        story_title = as_text(row.get("story_title") or row.get("title")).strip()
        if not story_title:
            story_title = f"Story {story_id}"

        normalized_story: Dict[str, Any] = {
            "story_id": story_id,
            "story_title": story_title,
            "priority": coerce_priority(row.get("priority"), idx),
            "story_points": normalize_positive_int(row.get("story_points")),
            "story_description": as_text(row.get("story_description")).strip(),
            "acceptance_criteria_items": [
                line.lstrip("-* \t").strip()
                for line in as_text(row.get("acceptance_criteria")).splitlines()
                if line.lstrip("-* \t").strip()
            ],
            "evaluated_invariant_ids": [
                str(item).strip()
                for item in (row.get("evaluated_invariant_ids") or [])
                if str(item).strip()
            ],
            "story_compliance_boundary_summaries": [
                str(item).strip()
                for item in (row.get("story_compliance_boundary_summaries") or [])
                if str(item).strip()
            ],
        }

        persona = as_text(row.get("persona")).strip() or None
        if persona:
            normalized_story["persona"] = persona

        source_req = as_text(row.get("source_requirement")).strip() or None
        if source_req:
            normalized_story["source_requirement"] = source_req

        stories.append(normalized_story)

    return {
        "success": True,
        "count": len(stories),
        "stories": stories,
        "excluded_counts": raw_result.get("excluded_counts") or {},
        "message": raw_result.get("message") or f"Found {len(stories)} sprint candidates.",
    }


def prepare_sprint_input_context(
    *,
    product_id: int,
    team_velocity_assumption: Any,
    sprint_duration_days: Any,
    user_context: Optional[str],
    max_story_points: Any,
    include_task_decomposition: Any,
    selected_story_ids: Optional[List[int]] = None,
    fetch_candidates: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build normalized SprintPlannerInput-compatible context from DB candidates."""
    candidate_result = load_sprint_candidates(
        product_id,
        fetch_candidates=fetch_candidates,
    )
    if not candidate_result.get("success"):
        return {
            "success": False,
            "error_code": candidate_result.get("error_code", "SPRINT_CANDIDATE_FETCH_FAILED"),
            "message": candidate_result.get("message", "Failed to fetch sprint candidates."),
            "candidate_result": candidate_result,
            "input_context": {},
        }

    candidate_rows = candidate_result.get("stories") or []
    if not candidate_rows:
        return {
            "success": False,
            "error_code": "SPRINT_CANDIDATES_MISSING",
            "message": "Only refined TO_DO stories are sprint-eligible. Refine stories first.",
            "candidate_result": candidate_result,
            "input_context": {},
        }

    normalized_selected_ids = normalize_selected_story_ids(selected_story_ids)
    selected_rows = candidate_rows
    if normalized_selected_ids:
        by_id = {
            int(row["story_id"]): row
            for row in candidate_rows
            if isinstance(row, dict) and normalize_positive_int(row.get("story_id")) is not None
        }
        invalid_ids = [story_id for story_id in normalized_selected_ids if story_id not in by_id]
        if invalid_ids:
            return {
                "success": False,
                "error_code": "SPRINT_SELECTION_INVALID",
                "message": (
                    "Some selected_story_ids are not refined TO_DO candidates: "
                    + ", ".join(str(item) for item in invalid_ids)
                ),
                "invalid_selected_ids": invalid_ids,
                "candidate_result": candidate_result,
                "input_context": {},
            }
        selected_rows = [by_id[story_id] for story_id in normalized_selected_ids]

    input_context: Dict[str, Any] = {
        "available_stories": [
            {
                "story_id": int(row["story_id"]),
                "story_title": row["story_title"],
                "priority": int(row["priority"]),
                "story_points": row.get("story_points"),
                "story_description": row.get("story_description", ""),
                "acceptance_criteria_items": list(row.get("acceptance_criteria_items") or []),
                "persona": row.get("persona"),
                "source_requirement": row.get("source_requirement"),
                "evaluated_invariant_ids": list(row.get("evaluated_invariant_ids") or []),
                "story_compliance_boundary_summaries": list(row.get("story_compliance_boundary_summaries") or []),
            }
            for row in selected_rows
            if isinstance(row, dict)
        ],
        "team_velocity_assumption": normalize_velocity(team_velocity_assumption),
        "sprint_duration_days": normalize_duration_days(sprint_duration_days),
        "max_story_points": normalize_positive_int(max_story_points),
        "include_task_decomposition": bool(include_task_decomposition),
    }

    normalized_user_context = as_text(user_context).strip()
    if normalized_user_context:
        input_context["user_context"] = normalized_user_context

    return {
        "success": True,
        "input_context": input_context,
        "candidate_result": candidate_result,
        "selected_story_ids": normalized_selected_ids,
    }
