# tools/orchestrator_tools.py
"""
Read-only tools for the orchestrator agent to make decisions.
These tools fetch project data from SQLite and transparently cache
small summaries in ADK's persistent session state to reduce latency.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, cast

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from agile_sqlmodel import CompiledSpecAuthority, Epic, Feature, Product, SpecRegistry, Theme, UserStory, StoryStatus, get_engine

# --- Cache configuration ---
CACHE_TTL_MINUTES: int = 5


def _utc_now_iso() -> str:
    """Return current UTC time in RFC3339/ISO format with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_params(params: Any) -> Dict[str, Any]:
    """Normalize tool params to a dict, handling wrapped JSON strings."""
    if params is None:
        return {}
    if isinstance(params, dict):
        params_dict: Dict[str, Any] = cast(Dict[str, Any], params)
        wrapped = params_dict.get("params")
        if isinstance(wrapped, dict):
            return cast(Dict[str, Any], wrapped)
        if isinstance(wrapped, str):
            try:
                parsed = json.loads(wrapped)
                return cast(Dict[str, Any], parsed) if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return params_dict
    if isinstance(params, str):
        try:
            parsed = json.loads(params)
            return cast(Dict[str, Any], parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


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
        select(UserStory.product_id, func.count(cast(Any, UserStory.story_id)))
        .where(cast(Any, UserStory.product_id).in_(product_ids))
        .group_by(cast(Any, UserStory.product_id))
    )

    # Map product_id -> count
    story_counts: Dict[int, int] = {
        pid: count for pid, count in session.exec(story_counts_query).all()
    }

    for product in products:
        projects.append(
            {
                "product_id": product.product_id,
                "name": product.name,
                "vision": product.vision or "(No vision set)",
                "roadmap": product.roadmap or "(No roadmap set)",
                "user_stories_count": story_counts.get(cast(int, product.product_id), 0),
            }
        )
    return len(projects), projects


def _refresh_projects_cache(state: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Hit the DB and update the persistent cache in `state`."""
    print("   [Cache] Cache miss or expired. Querying Database...")
    with Session(get_engine()) as session:
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
    parsed = CountProjectsInput.model_validate(_normalize_params(params))
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
    parsed = ListProjectsInput.model_validate(_normalize_params(params))
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
    with Session(get_engine()) as session:
        product = session.get(Product, product_id)
        if not product:
            print("   [DB] Product not found.")
            return {"success": False, "error": f"Product {product_id} not found"}

        # Optimized count queries using aggregations
        theme_count = session.exec(
            select(func.count(cast(Any, Theme.theme_id))).where(
                Theme.product_id == product_id
            )
        ).one()

        epic_count = session.exec(
            select(func.count(cast(Any, Epic.epic_id)))
            .join(Theme)
            .where(Theme.product_id == product_id)
        ).one()

        feature_count = session.exec(
            select(func.count(cast(Any, Feature.feature_id)))
            .join(Epic)
            .join(Theme)
            .where(Theme.product_id == product_id)
        ).one()

        story_count = session.exec(
            select(func.count(cast(Any, UserStory.story_id))).where(
                UserStory.product_id == product_id
            )
        ).one()

        latest_spec_version_id = session.exec(
            select(SpecRegistry.spec_version_id)
            .where(
                SpecRegistry.product_id == product_id,
                SpecRegistry.status == "approved",
            )
            .order_by(SpecRegistry.approved_at.desc(), SpecRegistry.spec_version_id.desc())
            .limit(1)
        ).first()

        print(f"   [DB] Success. Found '{product.name}'.")
        return {
            "success": True,
            "product": {
                "id": product.product_id,
                "name": product.name,
                "description": product.description,
                "vision": product.vision,
                "roadmap": product.roadmap,
                "technical_spec": product.technical_spec,
                "compiled_authority_json": product.compiled_authority_json,
                "spec_file_path": product.spec_file_path,
                "spec_loaded_at": product.spec_loaded_at.isoformat() if product.spec_loaded_at else None,
                "latest_spec_version_id": latest_spec_version_id,
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
    with Session(get_engine()) as session:
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


def fetch_product_backlog(product_id: int) -> Dict[str, Any]:
    """
    Fetch all 'To Do' user stories for a product.
    Returns a list of stories with basic details for sprint planning.
    """
    print(f"\n[Tool: fetch_product_backlog] Fetching backlog for product ID: {product_id}")
    with Session(get_engine()) as session:
        stories = session.exec(
            select(UserStory)
            .where(UserStory.product_id == product_id)
            .where(UserStory.status == StoryStatus.TO_DO)
            .order_by(UserStory.rank)
        ).all()

        if not stories:
            print("   [DB] No stories found.")
            return {"success": True, "count": 0, "stories": [], "message": "No stories found in backlog."}

        story_list = []
        for s in stories:
            story_list.append({
                "story_id": s.story_id,
                "title": s.title,
                "story_points": s.story_points,
                "priority": s.rank, # Using rank as proxy for priority if rank is integer-like or sortable
                "persona": s.persona
            })
        
        print(f"   [DB] Found {len(stories)} stories.")
        return {
            "success": True, 
            "count": len(stories), 
            "stories": story_list,
            "message": f"Found {len(stories)} stories in backlog."
        }


def load_specification_from_file(
    file_path: str,
    tool_context: Optional[ToolContext] = None,
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
        content = path.read_text(encoding='utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"File encoding error. Please ensure {file_path} is UTF-8 text."
        ) from exc

    # Log to state for transparency
    if tool_context and tool_context.state:
        state: Dict[str, Any] = cast(Dict[str, Any], tool_context.state)
        # Primary keys for authority gate fallback (must match keys used elsewhere)
        state["pending_spec_path"] = str(path.absolute())
        state["pending_spec_content"] = content

    print(f"[Tool: load_specification_from_file] Loaded {file_size_kb:.1f}KB from {path.name}")

    return content


def get_real_business_state() -> Dict[str, Any]:
    """
    Hydrates the initial session state by querying the Business DB.
    Used by main.py to seed the Orchestrator's memory before the session starts.
    """
    print("[*] Hydrating Session State from Business Database...")
    with Session(get_engine()) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)

    print(f"   Found {count} existing projects.")
    return {
        "projects_summary": count,
        "projects_list": projects,
        "projects_last_refreshed_utc": _utc_now_iso(),
        "current_context": "idle",
        "active_project": None,  # Tracks currently selected project
    }


def select_project(product_id: int, tool_context: ToolContext) -> Dict[str, Any]:
    """
    Agent tool: Select a project as the active context and load its full details
    into volatile memory. This sets the working context for subsequent operations.

    Hydrates all FSM-relevant state keys so that downstream phases
    (vision, backlog, sprint, roadmap, stories) can proceed without
    missing context:
        - active_project          (product dict + structure counts)
        - current_project_name
        - pending_spec_content    (spec text from DB column or disk)
        - pending_spec_path       (original file path if file-linked)
        - compiled_authority_cached
        - latest_spec_version_id
        - spec_persisted          (True when a spec is already linked)
        - current_context         ("project_selected")
    """
    print(f"\n[Tool: select_project] Setting project ID {product_id} as active...")

    # Get full project details
    details = get_project_details(product_id)

    if not details["success"]:
        print("   [Context] Failed to set active project.")
        return details

    # --- Populate session state ---
    state: Dict[str, Any] = cast(Dict[str, Any], tool_context.state)
    product_details = details["product"]

    # Core active-project snapshot
    state["active_project"] = {
        "product_id": product_id,
        "name": product_details["name"],
        "description": product_details.get("description"),
        "vision": product_details.get("vision"),
        "roadmap": product_details.get("roadmap"),
        "technical_spec": product_details.get("technical_spec"),
        "compiled_authority_json": product_details.get("compiled_authority_json"),
        "spec_file_path": product_details.get("spec_file_path"),
        "spec_loaded_at": product_details.get("spec_loaded_at"),
        "latest_spec_version_id": product_details.get("latest_spec_version_id"),
        "structure": details["structure"],
    }
    state["current_project_name"] = product_details["name"]

    # --- Specification hydration ---
    _hydrate_spec_state(state, product_details)

    # --- Compiled authority ---
    authority_json = product_details.get("compiled_authority_json")
    # Fallback: if Product column is null but a compiled authority exists in the
    # dedicated table, load it from there and backfill the Product column.
    if authority_json is None and product_details.get("latest_spec_version_id"):
        authority_json = _load_authority_fallback(
            product_id, product_details["latest_spec_version_id"]
        )
        if authority_json:
            # Update the snapshot so the return value is also correct
            state["active_project"]["compiled_authority_json"] = authority_json
    _set_or_clear(state, "compiled_authority_cached", authority_json)

    # --- Spec version ---
    _set_or_clear(state, "latest_spec_version_id", product_details.get("latest_spec_version_id"))

    # --- Guard: mark spec as already linked when applicable ---
    if product_details.get("spec_file_path") or product_details.get("technical_spec"):
        state["spec_persisted"] = True

    state["current_context"] = "project_selected"

    print(f"   [Context] Active project set to '{product_details['name']}'")

    return {
        "success": True,
        "active_project": state["active_project"],
        "message": f"Selected '{product_details['name']}' as active project",
    }


# ------------------------------------------------------------------
# Internal helpers for select_project state hydration
# ------------------------------------------------------------------

def _set_or_clear(state: Dict[str, Any], key: str, value: Any) -> None:
    """Set *key* in state when *value* is not None, otherwise delete it."""
    if value is not None:
        state[key] = value
    elif key in state:
        del state[key]


def _hydrate_spec_state(state: Dict[str, Any], product_details: Dict[str, Any]) -> None:
    """Populate pending_spec_content and pending_spec_path from DB or disk."""
    # 1. Inline blob takes precedence
    if product_details.get("technical_spec") is not None:
        state["pending_spec_content"] = product_details["technical_spec"]
        _set_or_clear(state, "pending_spec_path", product_details.get("spec_file_path"))
        return

    # 2. File-linked spec: read from disk
    spec_file = product_details.get("spec_file_path")
    if spec_file:
        _spec_path = Path(spec_file)
        state["pending_spec_path"] = spec_file
        if _spec_path.exists():
            try:
                state["pending_spec_content"] = _spec_path.read_text(encoding="utf-8")
                return
            except (OSError, UnicodeDecodeError):
                pass  # fall through to clear
        # File missing or unreadable
        if "pending_spec_content" in state:
            del state["pending_spec_content"]
        return

    # 3. No spec at all — clean up
    if "pending_spec_content" in state:
        del state["pending_spec_content"]
    if "pending_spec_path" in state:
        del state["pending_spec_path"]


def _load_authority_fallback(product_id: int, spec_version_id: int) -> Optional[str]:
    """
    Query CompiledSpecAuthority for the given spec version.  If none exists
    but the spec version is approved, trigger an on-demand compilation.
    Backfills Product.compiled_authority_json so future loads are instant.
    Returns the compiled-authority JSON string, or None.
    """
    with Session(get_engine()) as session:
        # 1. Try loading an existing compiled authority
        authority = session.exec(
            select(CompiledSpecAuthority)
            .where(CompiledSpecAuthority.spec_version_id == spec_version_id)
            .limit(1)
        ).first()
        if authority and authority.compiled_artifact_json:
            # Backfill the Product column
            product = session.get(Product, product_id)
            if product:
                product.compiled_authority_json = authority.compiled_artifact_json
                session.add(product)
                session.commit()
                print("   [Context] Backfilled compiled_authority_json from authority table")
            return authority.compiled_artifact_json

    # 2. No compiled authority exists — try to compile on demand
    try:
        from tools.spec_tools import compile_spec_authority_for_version, CompileSpecAuthorityForVersionInput
        print(f"   [Context] No compiled authority found — compiling spec version {spec_version_id}...")
        result = compile_spec_authority_for_version(
            CompileSpecAuthorityForVersionInput(
                spec_version_id=spec_version_id, force_recompile=False
            ),
            tool_context=None,
        )
        if result.get("success"):
            # Re-read the Product column which compile_spec just backfilled
            with Session(get_engine()) as session:
                product = session.get(Product, product_id)
                if product and product.compiled_authority_json:
                    print("   [Context] Compiled and cached authority on demand")
                    return product.compiled_authority_json
    except Exception as exc:
        print(f"   [Context] On-demand authority compilation failed: {exc}")

    return None
