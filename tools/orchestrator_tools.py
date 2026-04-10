# tools/orchestrator_tools.py
"""
Read-only tools for the orchestrator agent to make decisions.
These tools fetch project data from SQLite and transparently cache
small summaries in ADK's persistent session state to reduce latency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from models.core import Product, UserStory
from models.db import get_engine
from models.enums import StoryStatus
from services.orchestrator_context_service import (
    get_project_details as _get_project_details_service,
)
from services.orchestrator_context_service import (
    select_project as _select_project_service,
)
from services.orchestrator_query_service import (
    CACHE_TTL_MINUTES,
)
from services.orchestrator_query_service import (
    fetch_sprint_candidates as _fetch_sprint_candidates_service,
)
from services.orchestrator_query_service import (
    get_real_business_state as _get_real_business_state_service,
)
from services.orchestrator_query_service import (
    is_projects_cache_fresh as _is_projects_cache_fresh_service,
)
from services.orchestrator_query_service import (
    refresh_projects_cache as _refresh_projects_cache_service,
)
from services.orchestrator_query_service import (
    utc_now_iso as _utc_now_iso_service,
)


def _utc_now_iso() -> str:
    """Compatibility shim over the orchestrator query service helper."""
    return _utc_now_iso_service()


def _normalize_params(params: Any) -> dict[str, Any]:
    """Normalize tool params to a dict, handling wrapped JSON strings."""
    if params is None:
        return {}
    if isinstance(params, dict):
        params_dict: dict[str, Any] = cast("dict[str, Any]", params)
        wrapped = params_dict.get("params")
        if isinstance(wrapped, dict):
            return cast("dict[str, Any]", wrapped)
        if isinstance(wrapped, str):
            try:
                parsed = json.loads(wrapped)
                return (
                    cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}
                )
            except json.JSONDecodeError:
                return {}
        return params_dict
    if isinstance(params, str):
        try:
            parsed = json.loads(params)
            return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _is_fresh(state: dict[str, Any], ttl_minutes: int = CACHE_TTL_MINUTES) -> bool:
    """Compatibility shim over the orchestrator query service cache TTL helper."""
    return _is_projects_cache_fresh_service(state, ttl_minutes=ttl_minutes)


def _refresh_projects_cache(
    state: dict[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    """Compatibility shim over the orchestrator query service cache refresher."""
    return _refresh_projects_cache_service(state)


class CountProjectsInput(BaseModel):
    """Input schema for count_projects tool."""

    force_refresh: bool | None = Field(
        default=None,
        description=(
            "Force refresh from database, bypassing cache. "
            "Pass true if you suspect data changed."
        ),
    )


class ListProjectsInput(BaseModel):
    """Input schema for list_projects tool."""

    force_refresh: bool | None = Field(
        default=None,
        description=(
            "Force refresh from database, bypassing cache. "
            "Pass true if you suspect data changed."
        ),
    )


def count_projects(params: Any, tool_context: ToolContext) -> dict[str, Any]:
    """Agent tool: Count total projects. Uses a transparent persistent cache."""
    parsed = CountProjectsInput.model_validate(_normalize_params(params))
    should_refresh = bool(parsed.force_refresh)

    print(f"\n[Tool: count_projects] Refresh: {should_refresh}")

    state: dict[str, Any] = cast("dict[str, Any]", tool_context.state)

    if not should_refresh and _is_fresh(state) and "projects_summary" in state:
        count = int(state.get("projects_summary", 0))
        print(f"   [Cache] Hit! {count} projects.")
        return {
            "success": True,
            "count": count,
            "cached": True,
            "message": f"Found {count} project(s) in the cached snapshot",
        }

    count, _ = _refresh_projects_cache(state)
    print(f"   [DB] Read. {count} projects.")
    return {
        "success": True,
        "count": count,
        "cached": False,
        "message": f"Found {count} project(s) in the database",
    }


def list_projects(params: Any, tool_context: ToolContext) -> dict[str, Any]:
    """Agent tool: List all projects with summary info. Uses a transparent cache."""
    parsed = ListProjectsInput.model_validate(_normalize_params(params))
    should_refresh = bool(parsed.force_refresh)

    print(f"\n[Tool: list_projects] Request received. Force Refresh: {should_refresh}")

    state: dict[str, Any] = cast("dict[str, Any]", tool_context.state)

    if not should_refresh and _is_fresh(state) and "projects_list" in state:
        projects: list[dict[str, Any]] = list(state.get("projects_list", []))
        print(f"   [Cache] Hit! Returning {len(projects)} items.")
        return {
            "success": True,
            "count": len(projects),
            "projects": projects,
            "cached": True,
            "message": f"Listed {len(projects)} project(s) from cache",
        }

    count, projects = _refresh_projects_cache(state)
    print(f"   [DB] Read complete. Returning {len(projects)} items.")
    return {
        "success": True,
        "count": count,
        "projects": projects,
        "cached": False,
        "message": f"Listed {count} project(s) from the database",
    }


def get_project_details(product_id: int) -> dict[str, Any]:
    """Compatibility adapter over the orchestrator context service boundary."""
    return _get_project_details_service(product_id)


def get_project_by_name(project_name: str) -> dict[str, Any]:
    """Agent tool: Find a project by name."""
    print(f"\n[Tool: get_project_by_name] Searching for: '{project_name}'")
    with Session(get_engine()) as session:
        product = session.exec(
            select(Product).where(Product.name == project_name)
        ).first()
        if not product:
            print("   [DB] Not found.")
            return {
                "success": False,
                "error": f"Project '{project_name}' not found",
            }

        print(f"   [DB] Found ID: {product.product_id}")
        return {
            "success": True,
            "product_id": product.product_id,
            "product_name": product.name,
            "message": f"Found project '{project_name}' with ID {product.product_id}",
        }


def _priority_to_int(rank: str | None) -> int | None:
    """Convert story rank to integer priority when possible."""
    if rank is None:
        return None
    text = str(rank).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _story_order_key(story: UserStory) -> tuple[int, int]:
    """Sort key that keeps numeric rank first and stable ordering by story_id."""
    numeric_priority = _priority_to_int(story.rank)
    return (
        numeric_priority if numeric_priority is not None else 10_000,
        int(story.story_id or 0),
    )


def fetch_product_backlog(product_id: int) -> dict[str, Any]:
    """
    Fetch all 'To Do' user stories for a product.
    Returns a list of stories with basic details for inspection/diagnostics.
    """
    print(
        f"\n[Tool: fetch_product_backlog] Fetching backlog for product ID: {product_id}"
    )
    with Session(get_engine()) as session:
        stories = list(
            session.exec(
                select(UserStory)
                .where(UserStory.product_id == product_id)
                .where(UserStory.status == StoryStatus.TO_DO)
                .order_by(
                    cast("Any", UserStory.rank),
                    cast("Any", UserStory.story_id),
                )
            ).all()
        )
        stories.sort(key=_story_order_key)

        if not stories:
            print("   [DB] No stories found.")
            return {
                "success": True,
                "count": 0,
                "stories": [],
                "message": "No stories found in backlog.",
            }

        story_list = []
        for s in stories:
            priority = _priority_to_int(s.rank)
            story_list.append(
                {
                    "story_id": s.story_id,
                    "title": s.title,
                    "story_points": s.story_points,
                    "priority": s.rank,
                    "priority_numeric": priority,
                    "persona": s.persona,
                    "story_origin": s.story_origin,
                    "is_refined": bool(s.is_refined),
                    "is_superseded": bool(s.is_superseded),
                }
            )

        print(f"   [DB] Found {len(stories)} stories.")
        return {
            "success": True,
            "count": len(stories),
            "stories": story_list,
            "message": f"Found {len(stories)} stories in backlog.",
        }


def fetch_sprint_candidates(product_id: int) -> dict[str, Any]:
    """Compatibility adapter over the orchestrator query service boundary."""
    return _fetch_sprint_candidates_service(product_id)


def load_specification_from_file(
    file_path: str,
    tool_context: ToolContext | None = None,
) -> str:
    """
    Load a technical specification from a local file for project creation.

    Args:
        file_path: Absolute or relative path to specification file (.txt, .md, etc.)
        tool_context: Optional ADK context for state tracking

    Returns:
        Full text content of the specification file

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file exceeds size limit (100KB)

    Examples:
        - load_specification_from_file("docs/product_spec.md")
        - load_specification_from_file("C:/Users/dev/specs/feature.txt")
    """
    path = Path(file_path)

    # Validate existence
    if not path.exists():
        raise FileNotFoundError(
            f"Specification file not found: {file_path}\n"
            f"Please check the path and try again."
        )

    # Validate file size (prevent loading huge files)
    MAX_SIZE_KB = 100
    file_size_kb = path.stat().st_size / 1024
    if file_size_kb > MAX_SIZE_KB:
        raise ValueError(
            f"File too large ({file_size_kb:.1f}KB). "
            f"Maximum allowed: {MAX_SIZE_KB}KB.\n"
            f"Please use a smaller specification file."
        )

    # Read content
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"File encoding error. Please ensure {file_path} is UTF-8 text."
        ) from exc

    # Log to state for transparency
    if tool_context and tool_context.state:
        state: dict[str, Any] = cast("dict[str, Any]", tool_context.state)
        # Primary keys for authority gate fallback (must match keys used elsewhere)
        state["pending_spec_path"] = str(path.absolute())
        state["pending_spec_content"] = content

    print(
        f"[Tool: load_specification_from_file] Loaded {file_size_kb:.1f}KB from {path.name}"
    )

    return content


def get_real_business_state() -> dict[str, Any]:
    """Compatibility adapter over the orchestrator query service boundary."""
    return _get_real_business_state_service()


def select_project(product_id: int, tool_context: ToolContext) -> dict[str, Any]:
    """Compatibility adapter over the orchestrator context service boundary."""
    return _select_project_service(product_id, tool_context)
