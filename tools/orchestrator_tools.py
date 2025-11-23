# tools/orchestrator_tools.py
"""
Read-only tools for the orchestrator agent to make decisions.
These tools fetch project data from SQLite and transparently cache
small summaries in ADK's persistent session state to reduce latency.

Caching details:
- Cache keys: 'projects_summary', 'projects_list', 'projects_last_refreshed_utc'
- TTL: 5 minutes (configurable via CACHE_TTL_MINUTES)
- If no ToolContext is provided, tools bypass cache and hit the DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from google.adk.tools import ToolContext
from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Theme, UserStory, engine

# --- Cache configuration ---
CACHE_TTL_MINUTES: int = 5


# ---------- Internal utilities ----------


def _utc_now_iso() -> str:
    """Return current UTC time in RFC3339/ISO format with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_fresh(state: Dict[str, Any], ttl_minutes: int = CACHE_TTL_MINUTES) -> bool:
    """Return True if state['projects_last_refreshed_utc'] is within TTL."""
    ts: Optional[str] = state.get("projects_last_refreshed_utc")
    if not ts:
        return False
    last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last <= timedelta(minutes=ttl_minutes)


def _query_products(session: Session) -> List[Product]:
    """Fetch all products."""
    return session.exec(select(Product)).all()


def _build_projects_payload(
    session: Session, products: Iterable[Product]
) -> Tuple[int, List[Dict[str, Any]]]:
    """Build (count, projects_list) from DB rows."""
    projects: List[Dict[str, Any]] = []
    for product in products:
        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product.product_id)
        ).all()
        projects.append(
            {
                "product_id": product.product_id,
                "name": product.name,
                "vision": product.vision if product.vision else "(No vision set)",
                "roadmap": product.roadmap if product.roadmap else "(No roadmap set)",
                "user_stories_count": len(stories),
            }
        )
    return len(projects), projects


def _refresh_projects_cache(state: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Hit the DB and update the persistent cache in `state`."""
    with Session(engine) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)

    state["projects_summary"] = count
    state["projects_list"] = projects
    state["projects_last_refreshed_utc"] = _utc_now_iso()
    return count, projects


# ---------- Public tools (agent-facing) ----------


def count_projects(
    tool_context: Optional[ToolContext] = None, *, force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Agent tool: Count total projects. Uses a transparent persistent cache.

    Args:
        tool_context: ADK tool context (optional; enables caching).
        force_refresh: If True, bypass cache and refresh from DB.

    Returns:
        Dict with 'success', 'count', 'message' and 'cached' flags.
    """
    if tool_context is not None:
        state = tool_context.state
        if not force_refresh and _is_fresh(state) and "projects_summary" in state:
            count: int = int(state.get("projects_summary", 0))
            return {
                "success": True,
                "count": count,
                "cached": True,
                "message": f"Found {count} project(s) in the cached snapshot",
            }
        # Refresh cache from DB, then return
        count, _ = _refresh_projects_cache(state)
        return {
            "success": True,
            "count": count,
            "cached": False,
            "message": f"Found {count} project(s) in the database",
        }

    # No context (e.g., unit tests) → direct DB read
    with Session(engine) as session:
        products = _query_products(session)
        count = len(products)
        return {
            "success": True,
            "count": count,
            "cached": False,
            "message": f"Found {count} project(s) in the database",
        }


def list_projects(
    tool_context: Optional[ToolContext] = None, *, force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Agent tool: List all projects with summary info. Uses a transparent cache.

    Args:
        tool_context: ADK tool context (optional; enables caching).
        force_refresh: If True, bypass cache and refresh from DB.

    Returns:
        Dict with 'success', 'count', 'projects', 'message' and 'cached' flags.
    """
    if tool_context is not None:
        state = tool_context.state
        if not force_refresh and _is_fresh(state) and "projects_list" in state:
            projects: List[Dict[str, Any]] = list(state.get("projects_list", []))
            return {
                "success": True,
                "count": len(projects),
                "projects": projects,
                "cached": True,
                "message": f"Listed {len(projects)} project(s) from cache",
            }
        # Refresh cache from DB, then return
        count, projects = _refresh_projects_cache(state)
        return {
            "success": True,
            "count": count,
            "projects": projects,
            "cached": False,
            "message": f"Listed {count} project(s) from the database",
        }

    # No context (e.g., unit tests) → direct DB read
    with Session(engine) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)
        return {
            "success": True,
            "count": count,
            "projects": projects,
            "cached": False,
            "message": f"Listed {count} project(s) from the database",
        }


def get_project_details(product_id: int) -> Dict[str, Any]:
    """
    Agent tool: Get detailed breakdown of a project.

    Args:
        product_id: The product ID to query.

    Returns:
        Dict with:
          - product (id, name, vision, roadmap)
          - structure (themes, epics, features, user_stories)
          - message string
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {"success": False, "error": f"Product {product_id} not found"}

        themes = session.exec(select(Theme).where(Theme.product_id == product_id)).all()
        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()

        total_epics = 0
        total_features = 0
        for theme in themes:
            epics = session.exec(
                select(Epic).where(Epic.theme_id == theme.theme_id)
            ).all()
            total_epics += len(epics)
            for epic in epics:
                features = session.exec(
                    select(Feature).where(Feature.epic_id == epic.epic_id)
                ).all()
                total_features += len(features)

        return {
            "success": True,
            "product": {
                "id": product.product_id,
                "name": product.name,
                "vision": product.vision,
                "roadmap": product.roadmap,
            },
            "structure": {
                "themes": len(themes),
                "epics": total_epics,
                "features": total_features,
                "user_stories": len(stories),
            },
            "message": (
                f"Project '{product.name}' has {len(themes)} theme(s), "
                f"{total_epics} epic(s), {total_features} feature(s), "
                f"{len(stories)} story(ies)"
            ),
        }


def get_project_by_name(project_name: str) -> Dict[str, Any]:
    """
    Agent tool: Find a project by name.

    Args:
        project_name: Name to search for.

    Returns:
        Dict with 'success' and, if found, 'product_id' and 'product_name'.
    """
    with Session(engine) as session:
        product = session.exec(
            select(Product).where(Product.name == project_name)
        ).first()

        if not product:
            return {"success": False, "error": f"Project '{project_name}' not found"}

        return {
            "success": True,
            "product_id": product.product_id,
            "product_name": product.name,
            "message": f"Found project '{project_name}' with ID {product.product_id}",
        }
