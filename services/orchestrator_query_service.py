"""Read/query service helpers previously embedded in tools.orchestrator_tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple, cast

from sqlalchemy import func
from sqlmodel import Session, select

from models.db import get_engine
from models.core import Product
from models.core import Sprint
from models.core import SprintStory
from models.core import UserStory
from models.enums import SprintStatus, StoryStatus
from utils.spec_schemas import ValidationEvidence

CACHE_TTL_MINUTES: int = 5


def utc_now_iso() -> str:
    """Return current UTC time in RFC3339/ISO format with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_projects_cache_fresh(
    state: Dict[str, Any],
    ttl_minutes: int = CACHE_TTL_MINUTES,
) -> bool:
    """Return True if the cached projects snapshot is within the TTL window."""
    ts = state.get("projects_last_refreshed_utc")
    if not ts:
        return False
    last = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last <= timedelta(minutes=ttl_minutes)


def _query_products(session: Session) -> List[Product]:
    """Fetch all products."""
    return list(session.exec(select(Product)).all())


def _story_evaluated_invariant_ids(story: UserStory) -> List[str]:
    """Return the evaluated invariant IDs already validated for a story."""
    if not story.validation_evidence:
        return []
    try:
        evidence = ValidationEvidence.model_validate_json(story.validation_evidence)
    except Exception:  # pylint: disable=broad-except
        return []
    return list(evidence.evaluated_invariant_ids or [])


def _story_compliance_boundary_summaries(story: UserStory) -> List[str]:
    """Return the evaluated compliance boundaries for a story."""
    if not story.validation_evidence:
        return []
    try:
        evidence = ValidationEvidence.model_validate_json(story.validation_evidence)
    except Exception:  # pylint: disable=broad-except
        return []

    findings = evidence.alignment_failures + evidence.alignment_warnings
    return [finding.message for finding in findings if finding.message]


def _priority_to_int(rank: str | None) -> int:
    """Convert legacy string rank to a comparable integer."""
    if rank is None:
        return 999
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 999


def _story_order_key(story: UserStory) -> Tuple[int, int]:
    """Stable ordering for story query results."""
    story_id = cast(int, story.story_id or 0)
    return (_priority_to_int(story.rank), story_id)


def _build_projects_payload(
    session: Session,
    products: Iterable[Product],
) -> Tuple[int, List[Dict[str, Any]]]:
    """Build (count, projects_list) from DB rows."""
    projects: List[Dict[str, Any]] = []
    product_ids = [product.product_id for product in products]

    if not product_ids:
        return 0, []

    story_counts_query = (
        select(UserStory.product_id, func.count(cast(Any, UserStory.story_id)))
        .where(cast(Any, UserStory.product_id).in_(product_ids))
        .group_by(cast(Any, UserStory.product_id))
    )
    sprint_counts_query = (
        select(Sprint.product_id, func.count(cast(Any, Sprint.sprint_id)))
        .where(cast(Any, Sprint.product_id).in_(product_ids))
        .group_by(cast(Any, Sprint.product_id))
    )

    story_counts: Dict[int, int] = {
        pid: count for pid, count in session.exec(story_counts_query).all()
    }
    sprint_counts: Dict[int, int] = {
        pid: count for pid, count in session.exec(sprint_counts_query).all()
    }

    for product in products:
        product_id = cast(int, product.product_id)
        projects.append(
            {
                "product_id": product_id,
                "name": product.name,
                "vision": product.vision or "(No vision set)",
                "roadmap": product.roadmap or "(No roadmap set)",
                "user_stories_count": story_counts.get(product_id, 0),
                "sprint_count": sprint_counts.get(product_id, 0),
            }
        )
    return len(projects), projects


def refresh_projects_cache(
    state: Dict[str, Any],
) -> Tuple[int, List[Dict[str, Any]]]:
    """Hit the DB and update the persistent projects cache in state."""
    print("   [Cache] Cache miss or expired. Querying Database...")
    with Session(get_engine()) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)

    state["projects_summary"] = count
    state["projects_list"] = projects
    state["projects_last_refreshed_utc"] = utc_now_iso()
    return count, projects


def fetch_sprint_candidates(product_id: int) -> Dict[str, Any]:
    """
    Fetch sprint-eligible stories for a product.

    Eligibility rule:
    - status == TO_DO
    - is_refined == True
    - is_superseded == False
    """
    print(
        f"\n[Tool: fetch_sprint_candidates] Fetching refined sprint candidates for product ID: {product_id}"
    )
    with Session(get_engine()) as session:
        open_sprint_story_ids = {
            int(story_id)
            for story_id in session.exec(
                select(SprintStory.story_id)
                .join(Sprint, Sprint.sprint_id == SprintStory.sprint_id)
                .where(
                    Sprint.product_id == product_id,
                    Sprint.status.in_([SprintStatus.PLANNED, SprintStatus.ACTIVE]),
                )
            ).all()
            if story_id is not None
        }
        stories = list(
            session.exec(
                select(UserStory)
                .where(UserStory.product_id == product_id)
                .where(UserStory.status == StoryStatus.TO_DO)
                .order_by(UserStory.rank, UserStory.story_id)
            ).all()
        )

    if not stories:
        print("   [DB] No stories found.")
        return {
            "success": True,
            "count": 0,
            "stories": [],
            "excluded_counts": {
                "non_refined": 0,
                "superseded": 0,
                "open_sprint": 0,
            },
            "message": "No stories found in backlog.",
        }

    refined: List[UserStory] = []
    excluded_non_refined = 0
    excluded_superseded = 0
    excluded_open_sprint = 0

    for story in stories:
        if bool(story.is_superseded):
            excluded_superseded += 1
            continue
        if not bool(story.is_refined):
            excluded_non_refined += 1
            continue
        if int(story.story_id or 0) in open_sprint_story_ids:
            excluded_open_sprint += 1
            continue
        refined.append(story)

    refined.sort(key=_story_order_key)

    candidate_list: List[Dict[str, Any]] = []
    for story in refined:
        candidate_list.append(
            {
                "story_id": story.story_id,
                "story_title": story.title,
                "priority": _priority_to_int(story.rank),
                "story_points": story.story_points,
                "persona": story.persona,
                "source_requirement": story.source_requirement,
                "story_origin": story.story_origin,
                "story_description": story.story_description,
                "acceptance_criteria": story.acceptance_criteria,
                "evaluated_invariant_ids": _story_evaluated_invariant_ids(story),
                "story_compliance_boundary_summaries": _story_compliance_boundary_summaries(
                    story
                ),
            }
        )

    print(
        "   [DB] Found %s sprint candidates (excluded: non_refined=%s, superseded=%s, open_sprint=%s)."
        % (
            len(candidate_list),
            excluded_non_refined,
            excluded_superseded,
            excluded_open_sprint,
        )
    )

    return {
        "success": True,
        "count": len(candidate_list),
        "stories": candidate_list,
        "excluded_counts": {
            "non_refined": excluded_non_refined,
            "superseded": excluded_superseded,
            "open_sprint": excluded_open_sprint,
        },
        "message": (
            f"Found {len(candidate_list)} refined sprint candidate(s) in backlog "
            f"(excluded non-refined={excluded_non_refined}, superseded={excluded_superseded}, "
            f"open_sprint={excluded_open_sprint})."
        ),
    }


def get_real_business_state() -> Dict[str, Any]:
    """
    Hydrate the initial session state by querying the business database.
    """
    print("[*] Hydrating Session State from Business Database...")
    with Session(get_engine()) as session:
        products = _query_products(session)
        count, projects = _build_projects_payload(session, products)

    print(f"   Found {count} existing projects.")
    return {
        "projects_summary": count,
        "projects_list": projects,
        "projects_last_refreshed_utc": utc_now_iso(),
        "current_context": "idle",
        "active_project": None,
    }
