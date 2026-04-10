"""Tools for the User Story Writer agent."""

import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from models.core import Product, UserStory
from models.db import get_engine
from models.enums import WorkflowEventType
from models.events import WorkflowEvent
from orchestrator_agent.agent_tools.story_linkage import (
    normalize_requirement_key,
    title_changed_significantly,
)

from .schemes import UserStoryItem

logger = logging.getLogger(__name__)


class SaveStoriesInput(BaseModel):
    """Input schema for save_stories_tool."""

    product_id: Annotated[
        int,
        Field(description="The product ID to attach stories to."),
    ]
    parent_requirement: Annotated[
        str,
        Field(description="The roadmap requirement these stories decompose."),
    ]
    stories: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "List of approved story dicts from user_story_writer_tool output. "
                "Each must have: story_title, statement, acceptance_criteria, invest_score."
            ),
        ),
    ]


def _extract_persona(statement: str) -> str | None:
    """Extract the persona/role from 'As a [role], I want ...' format.

    Args:
        statement: Full story statement string.

    Returns:
        Extracted role string, or None if format does not match.
    """
    match = re.match(r"[Aa]s\s+(?:a|an)\s+(.+?),\s+I\s+want", statement)
    if match:
        return match.group(1).strip()
    return None


def _format_acceptance_criteria(criteria: list[str]) -> str:
    return "\n".join(f"- {c}" if not c.startswith("- ") else c for c in criteria)


def _upsert_refined_story(
    session: Session,
    *,
    product_id: int,
    normalized_req: str,
    slot: int,
    item: UserStoryItem,
) -> tuple[int, str]:
    """Upsert a refined story by deterministic linkage key."""
    existing = session.exec(
        select(UserStory)
        .where(UserStory.product_id == product_id)
        .where(UserStory.source_requirement == normalized_req)
        .where(UserStory.refinement_slot == slot)
        .where(UserStory.is_superseded == False)  # noqa: E712
    ).first()

    persona = _extract_persona(item.statement)
    ac_text = _format_acceptance_criteria(item.acceptance_criteria)

    if existing:
        if title_changed_significantly(existing.title, item.story_title):
            logger.warning(
                "refinement.slot_title_drift product_id=%s requirement=%s slot=%s old=%r new=%r",
                product_id,
                normalized_req,
                slot,
                existing.title,
                item.story_title,
            )

        if (not (existing.acceptance_criteria or "").strip()) and (
            existing.original_acceptance_criteria is None
        ):
            existing.original_acceptance_criteria = existing.acceptance_criteria

        existing.title = item.story_title
        existing.story_description = item.statement
        existing.acceptance_criteria = ac_text
        existing.persona = persona
        existing.story_origin = "refined"
        existing.is_refined = True
        existing.is_superseded = False
        existing.ac_updated_at = datetime.now(UTC)
        existing.ac_update_reason = "user_story_refinement"
        session.add(existing)
        session.flush()
        existing_story_id = existing.story_id
        if existing_story_id is None:
            raise RuntimeError("Existing story ID was not generated.")
        return existing_story_id, "updated"

    story = UserStory(
        product_id=product_id,
        title=item.story_title,
        story_description=item.statement,
        acceptance_criteria=ac_text,
        persona=persona,
        source_requirement=normalized_req,
        refinement_slot=slot,
        story_origin="refined",
        is_refined=True,
        is_superseded=False,
        ac_update_reason="user_story_refinement",
    )
    session.add(story)
    session.flush()
    story_id = story.story_id
    if story_id is None:
        raise RuntimeError("Story ID was not generated.")
    return story_id, "created"


def save_stories_tool(
    input_data: SaveStoriesInput,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """
    Persist approved user stories to the database.

    Validates each story against UserStoryItem schema, creates UserStory
    rows linked to the given product_id, and extracts persona from statement.

    Args:
        input_data: Stories payload with product_id and story list.
        tool_context: Optional ADK context for session state storage.

    Returns:
        Dict with success status, saved count, and created story IDs.
    """
    engine = get_engine()
    start_ts = time.perf_counter()

    with Session(engine) as session:
        # Verify product exists
        product = session.exec(
            select(Product).where(Product.product_id == input_data.product_id)
        ).first()

        if not product:
            return {
                "success": False,
                "error": f"Product with ID {input_data.product_id} not found.",
            }

        # Validate each story against schema
        validated: list[UserStoryItem] = []
        validation_errors: list[str] = []

        for idx, story_dict in enumerate(input_data.stories):
            try:
                item = UserStoryItem.model_validate(story_dict)
                validated.append(item)
            except ValidationError as e:
                errors = []
                for err in e.errors():
                    loc = err.get("loc", ())
                    prefix = str(loc[0]) if loc else "(model)"
                    errors.append(f"{prefix}: {err['msg']}")
                validation_errors.append(f"Story {idx + 1}: {'; '.join(errors)}")

        if validation_errors:
            return {
                "success": False,
                "error": f"Validation errors: {'; '.join(validation_errors)}",
                "valid_count": len(validated),
                "invalid_count": len(validation_errors),
            }

        # Persist to database via deterministic linkage upsert
        normalized_req = normalize_requirement_key(input_data.parent_requirement)
        created_ids: list[int] = []
        updated_ids: list[int] = []

        seeded_slots = session.exec(
            select(UserStory.story_id)
            .where(UserStory.product_id == input_data.product_id)
            .where(UserStory.source_requirement == normalized_req)
            .where(UserStory.is_superseded == False)  # noqa: E712
        ).all()

        for idx, item in enumerate(validated, start=1):
            story_id, action = _upsert_refined_story(
                session,
                product_id=input_data.product_id,
                normalized_req=normalized_req,
                slot=idx,
                item=item,
            )
            if action == "created":
                created_ids.append(story_id)
            else:
                updated_ids.append(story_id)

        if len(validated) < len(seeded_slots):
            logger.warning(
                "refinement.slot_underflow product_id=%s requirement=%s refined_count=%s seeded_count=%s",
                input_data.product_id,
                input_data.parent_requirement,
                len(validated),
                len(seeded_slots),
            )

        duration_seconds = None
        if tool_context and tool_context.state:
            duration_seconds = tool_context.state.get("story_refinement_duration")
        if duration_seconds is None:
            duration_seconds = round(time.perf_counter() - start_ts, 3)
        session_id = getattr(tool_context, "session_id", None) if tool_context else None
        event_metadata = json.dumps(
            {
                "parent_requirement": input_data.parent_requirement,
                "saved_count": len(updated_ids) + len(created_ids),
                "updated_count": len(updated_ids),
                "created_count": len(created_ids),
            }
        )
        session.add(
            WorkflowEvent(
                event_type=WorkflowEventType.STORIES_SAVED,
                product_id=input_data.product_id,
                session_id=session_id,
                duration_seconds=float(duration_seconds),
                event_metadata=event_metadata,
            )
        )
        session.commit()

        # Optionally store in session state for downstream use
        if tool_context:
            saved_key = f"stories_{input_data.parent_requirement}"
            tool_context.state[saved_key] = {
                "product_id": input_data.product_id,
                "parent_requirement": input_data.parent_requirement,
                "story_ids": sorted(updated_ids + created_ids),
                "count": len(updated_ids) + len(created_ids),
            }

        print(
            f"\n\033[92m[Stories Saved]\033[0m "
            f"{len(updated_ids) + len(created_ids)} stories for '{input_data.parent_requirement}' "
            f"(updated={len(updated_ids)}, created={len(created_ids)})"
        )

        return {
            "success": True,
            "product_id": input_data.product_id,
            "parent_requirement": input_data.parent_requirement,
            "saved_count": len(updated_ids) + len(created_ids),
            "updated_count": len(updated_ids),
            "created_count": len(created_ids),
            "updated_story_ids": updated_ids,
            "created_story_ids": created_ids,
            "story_ids": sorted(updated_ids + created_ids),
            "message": (
                f"{len(updated_ids) + len(created_ids)} user stories saved for "
                f"'{input_data.parent_requirement}'."
            ),
        }


__all__ = ["SaveStoriesInput", "save_stories_tool"]
