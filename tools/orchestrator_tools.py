# tools/orchestrator_tools.py
"""
Read-only tools for the orchestrator agent to make decisions.
These tools fetch project data from SQLite and transparently cache
small summaries in ADK's persistent session state to reduce latency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Theme, UserStory, engine

# --- Cache configuration ---
CACHE_TTL_MINUTES: int = 5


def _utc_now_iso() -> str:
    """Return current UTC time in RFC3339/ISO format with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_fresh(state: Dict[str, Any], ttl_minutes: int = CACHE_TTL_MINUTES) -> bool:
    """Return True if state['projects_last_refreshed_utc'] is within TTL."""
    ts = state.get("projects_last_refreshed_utc")
    if not ts:
        return False
    last = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last <= timedelta(minutes=ttl_minutes)


def _query_products(session: Session) -> List[Product]:
    """Fetch all products."""
    return list(session.exec(select(Product)).all())


def _build_projects_payload(
    session: Session, products: Iterable[Product]
) -> Tuple[int, List[Dict[str, Any]]]:
    """Build (count, projects_list) from DB rows."""
    projects: List[Dict[str, Any]] = []

    # 1. Collect product IDs
    product_ids = [p.product_id for p in products]

    if not product_ids:
        return 0, []

    # 2. Fetch counts in one query
    story_counts_query = (
        select(UserStory.product_id, func.count(UserStory.story_id))
        .where(UserStory.product_id.in_(product_ids))
        .group_by(UserStory.product_id)
    )

    # Map product_id -> count
    story_counts = {
        pid: count for pid, count in session.exec(story_counts_query).all()
    }

    for product in products:
        projects.append(
            {
                "product_id": product.product_id,
                "name": product.name,
                "vision": product.vision or "(No vision set)",
                "roadmap": product.roadmap or "(No roadmap set)",
                "user_stories_count": story_counts.get(product.product_id, 0),
            }
        )
    return len(projects), projects


def _refresh_projects_cache(state: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Hit the DB and update the persistent cache in `state`."""
    print("   [Cache] Cache miss or expired. Querying Database...")
    with Session(engine) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)

    state["projects_summary"] = count
    state["projects_list"] = projects
    state["projects_last_refreshed_utc"] = _utc_now_iso()
    return count, projects


class CountProjectsInput(BaseModel):
    """Input schema for count_projects tool."""

    force_refresh: Optional[bool] = Field(
        default=None,
        description=(
            "Force refresh from database, bypassing cache. "
            "Pass true if you suspect data changed."
        ),
    )


class ListProjectsInput(BaseModel):
    """Input schema for list_projects tool."""

    force_refresh: Optional[bool] = Field(
        default=None,
        description=(
            "Force refresh from database, bypassing cache. "
            "Pass true if you suspect data changed."
        ),
    )


def count_projects(params: Any, tool_context: ToolContext) -> Dict[str, Any]:
    """Agent tool: Count total projects. Uses a transparent persistent cache."""
    parsed = CountProjectsInput.model_validate(params or {})
    should_refresh = bool(parsed.force_refresh)

    print(f"\n[Tool: count_projects] Refresh: {should_refresh}")

    state: Dict[str, Any] = cast(Dict[str, Any], tool_context.state)

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


def list_projects(params: Any, tool_context: ToolContext) -> Dict[str, Any]:
    """Agent tool: List all projects with summary info. Uses a transparent cache."""
    parsed = ListProjectsInput.model_validate(params or {})
    should_refresh = bool(parsed.force_refresh)

    print(f"\n[Tool: list_projects] Request received. Force Refresh: {should_refresh}")

    state: Dict[str, Any] = cast(Dict[str, Any], tool_context.state)

    if not should_refresh and _is_fresh(state) and "projects_list" in state:
        projects: List[Dict[str, Any]] = list(state.get("projects_list", []))
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


def get_project_details(product_id: int) -> Dict[str, Any]:
    """Agent tool: Get detailed breakdown of a project."""
    print(f"\n[Tool: get_project_details] Querying ID: {product_id}")
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            print("   [DB] Product not found.")
            return {"success": False, "error": f"Product {product_id} not found"}

        # Optimized count queries using aggregations
        theme_count = session.exec(
            select(func.count(Theme.theme_id)).where(Theme.product_id == product_id)
        ).one()

        epic_count = session.exec(
            select(func.count(Epic.epic_id))
            .join(Theme)
            .where(Theme.product_id == product_id)
        ).one()

        feature_count = session.exec(
            select(func.count(Feature.feature_id))
            .join(Epic)
            .join(Theme)
            .where(Theme.product_id == product_id)
        ).one()

        story_count = session.exec(
            select(func.count(UserStory.story_id)).where(
                UserStory.product_id == product_id
            )
        ).one()

        print(f"   [DB] Success. Found '{product.name}'.")
        return {
            "success": True,
            "product": {
                "id": product.product_id,
                "name": product.name,
                "vision": product.vision,
                "roadmap": product.roadmap,
            },
            "structure": {
                "themes": theme_count,
                "epics": epic_count,
                "features": feature_count,
                "user_stories": story_count,
            },
            "message": (
                f"Project '{product.name}' has {theme_count} theme(s), "
                f"{epic_count} epic(s), {feature_count} feature(s), "
                f"{story_count} story(ies)"
            ),
        }


def get_project_by_name(project_name: str) -> Dict[str, Any]:
    """Agent tool: Find a project by name."""
    print(f"\n[Tool: get_project_by_name] Searching for: '{project_name}'")
    with Session(engine) as session:
        product = session.exec(select(Product).where(Product.name == project_name)).first()
        if not product:
            print("   [DB] Not found.")
            return {"success": False, "error": f"Project '{project_name}' not found"}

        print(f"   [DB] Found ID: {product.product_id}")
        return {
            "success": True,
            "product_id": product.product_id,
            "product_name": product.name,
            "message": f"Found project '{project_name}' with ID {product.product_id}",
        }


def get_real_business_state() -> Dict[str, Any]:
    """
    Hydrates the initial session state by querying the Business DB.
    Used by main.py to seed the Orchestrator's memory before the session starts.
    """
    print("[*] Hydrating Session State from Business Database...")
    with Session(engine) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)

    print(f"   Found {count} existing projects.")
    return {
        "projects_summary": count,
        "projects_list": projects,
        "projects_last_refreshed_utc": _utc_now_iso(),
        "current_context": "idle",
        "active_project": None,  # Tracks currently selected project
        "vision_artifacts": [],
        "last_tool_output": None,
    }


def select_project(product_id: int, tool_context: ToolContext) -> Dict[str, Any]:
    """
    Agent tool: Select a project as the active context and load its full details
    into volatile memory. This sets the working context for subsequent operations.
    """
    print(f"\n[Tool: select_project] Setting project ID {product_id} as active...")
    
    # Get full project details
    details = get_project_details(product_id)
    
    if not details["success"]:
        print("   [Context] Failed to set active project.")
        return details
    
    # Store in volatile memory
    state: Dict[str, Any] = cast(Dict[str, Any], tool_context.state)
    state["active_project"] = {
        "product_id": product_id,
        "name": details["product"]["name"],
        "vision": details["product"]["vision"],
        "roadmap": details["product"]["roadmap"],
        "structure": details["structure"],
    }
    state["current_context"] = "project_selected"
    
    print(f"   [Context] Active project set to '{details['product']['name']}'")
    
    return {
        "success": True,
        "active_project": state["active_project"],
        "message": f"Selected '{details['product']['name']}' as active project",
    }

