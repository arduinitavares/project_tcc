# tools/orchestrator_tools.py
"""
Read-only tools for the orchestrator agent to make decisions.
These tools fetch project data from SQLite and transparently cache
small summaries in ADK's persistent session state to reduce latency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, Iterable, List, Optional, Tuple, cast

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Theme, UserStory, engine

# --- Cache configuration ---
CACHE_TTL_MINUTES: int = 5


# ---------- Internal utilities ----------


def _utc_now_iso() -> str:
    """Return current UTC time in RFC3339/ISO format with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_fresh(
    state: Dict[str, Any], ttl_minutes: int = CACHE_TTL_MINUTES
) -> bool:
    """Return True if state['projects_last_refreshed_utc'] is within TTL."""
    ts: str | None = state.get("projects_last_refreshed_utc")
    if not ts:
        return False
    last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last <= timedelta(minutes=ttl_minutes)


def _query_products(session: Session) -> List[Product]:
    """Fetch all products."""
    return list(session.exec(select(Product)).all())


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
                "vision": (
                    product.vision if product.vision else "(No vision set)"
                ),
                "roadmap": (
                    product.roadmap if product.roadmap else "(No roadmap set)"
                ),
                "user_stories_count": len(stories),
            }
        )
    return len(projects), projects


def _refresh_projects_cache(
    state: Dict[str, Any],
) -> Tuple[int, List[Dict[str, Any]]]:
    """Hit the DB and update the persistent cache in `state`."""
    print("   [Cache] Cache miss or expired. Querying Database...")
    with Session(engine) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)

    state["projects_summary"] = count
    state["projects_list"] = projects
    state["projects_last_refreshed_utc"] = _utc_now_iso()
    return count, projects


# ---------- Public tools (agent-facing) ----------


class CountProjectsInput(BaseModel):
    """Input schema for count_projects tool."""

    force_refresh: Annotated[
        Optional[bool],
        Field(
            description="Force refresh from database, bypassing cache. Pass true if you suspect data changed."
        ),
    ]


class ListProjectsInput(BaseModel):
    """Input schema for list_projects tool."""

    force_refresh: Annotated[
        Optional[bool],
        Field(
            description="Force refresh from database, bypassing cache. Pass true if you suspect data changed."
        ),
    ]


def count_projects(
    params: CountProjectsInput, tool_context: ToolContext
) -> Dict[str, Any]:
    """
    Agent tool: Count total projects. Uses a transparent persistent cache.
    """
    should_refresh = (
        params.force_refresh if params.force_refresh is not None else False
    )

    print(f"\n[Tool: count_projects] Refresh: {should_refresh}")

    state: Dict[str, Any] = cast(Dict[str, Any], tool_context.state)

    if not should_refresh and _is_fresh(state) and "projects_summary" in state:
        count: int = int(state.get("projects_summary", 0))
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


def list_projects(
    params: ListProjectsInput, tool_context: ToolContext
) -> Dict[str, Any]:
    """
    Agent tool: List all projects with summary info. Uses a transparent cache.
    """
    should_refresh = (
        params.force_refresh if params.force_refresh is not None else False
    )

    print(
        f"\n[Tool: list_projects] Request received. Force Refresh: {should_refresh}"
    )

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

    # Refresh cache from DB
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
    """
    Agent tool: Get detailed breakdown of a project.
    """
    print(f"\n[Tool: get_project_details] Querying ID: {product_id}")
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            print("   [DB] Product not found.")
            return {
                "success": False,
                "error": f"Product {product_id} not found",
            }

        # ... (Rest of logic remains the same, queries sub-tables)
        themes = session.exec(
            select(Theme).where(Theme.product_id == product_id)
        ).all()
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
    """
    print(f"\n[Tool: get_project_by_name] Searching for: '{project_name}'")
    with Session(engine) as session:
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


# ---------- Initialization Helper (Used by main.py) ----------


def get_real_business_state() -> Dict[str, Any]:
    """
    Hydrates the initial session state by querying the Business DB.
    Used by main.py to seed the Orchestrator's memory before the session starts.
    """
    print("🔍 Hydrating Session State from Business Database...")
    try:
        with Session(engine) as session:
            products = _query_products(session)
            count, projects = _build_projects_payload(session, products)

        print(f"   Found {count} existing projects.")

        return {
            "projects_summary": count,
            "projects_list": projects,
            "current_context": "idle",
            "vision_artifacts": [],
            "last_tool_output": None,
        }
    except Exception as e:
        print(f"⚠️ Warning: Could not read DB for initial state: {e}")
        # Return safe default state on error
        return {
            "projects_summary": 0,
            "projects_list": [],
            "current_context": "error_hydrating",
        }
