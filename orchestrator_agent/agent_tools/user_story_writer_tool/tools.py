"""Tools for the User Story Writer agent."""

import re
from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from agile_sqlmodel import Product, UserStory, get_engine
from .schemes import UserStoryItem


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
        List[Dict[str, Any]],
        Field(
            description=(
                "List of approved story dicts from user_story_writer_tool output. "
                "Each must have: story_title, statement, acceptance_criteria, invest_score."
            ),
        ),
    ]


def _extract_persona(statement: str) -> Optional[str]:
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


def save_stories_tool(
    input_data: SaveStoriesInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
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
        validated: List[UserStoryItem] = []
        validation_errors: List[str] = []

        for idx, story_dict in enumerate(input_data.stories):
            try:
                item = UserStoryItem.model_validate(story_dict)
                validated.append(item)
            except ValidationError as e:
                errors = [
                    f"{err['loc'][0]}: {err['msg']}" for err in e.errors()
                ]
                validation_errors.append(f"Story {idx + 1}: {'; '.join(errors)}")

        if validation_errors:
            return {
                "success": False,
                "error": f"Validation errors: {'; '.join(validation_errors)}",
                "valid_count": len(validated),
                "invalid_count": len(validation_errors),
            }

        # Persist to database
        created_ids: List[int] = []
        for item in validated:
            persona = _extract_persona(item.statement)
            ac_text = "\n".join(
                f"- {c}" if not c.startswith("- ") else c
                for c in item.acceptance_criteria
            )
            story = UserStory(
                product_id=input_data.product_id,
                title=item.story_title,
                story_description=item.statement,
                acceptance_criteria=ac_text,
                persona=persona,
            )
            session.add(story)
            session.flush()
            created_ids.append(story.story_id)

        session.commit()

        # Optionally store in session state for downstream use
        if tool_context:
            saved_key = f"stories_{input_data.parent_requirement}"
            tool_context.state[saved_key] = {
                "product_id": input_data.product_id,
                "parent_requirement": input_data.parent_requirement,
                "story_ids": created_ids,
                "count": len(created_ids),
            }

        print(
            f"\n\033[92m[Stories Saved]\033[0m "
            f"{len(created_ids)} stories for '{input_data.parent_requirement}'"
        )

        return {
            "success": True,
            "product_id": input_data.product_id,
            "parent_requirement": input_data.parent_requirement,
            "saved_count": len(created_ids),
            "story_ids": created_ids,
            "message": (
                f"{len(created_ids)} user stories saved for "
                f"'{input_data.parent_requirement}'."
            ),
        }


__all__ = ["SaveStoriesInput", "save_stories_tool"]
