"""Tools for backlog_primer agent."""

from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from agile_sqlmodel import UserStory, StoryStatus, get_engine


from .schemes import BacklogItem


class SaveBacklogInput(BaseModel):
    """Input schema for save_backlog_tool."""

    product_id: Annotated[int, Field(description="The product ID.")]
    backlog_items: Annotated[
        List[Dict[str, Any]],
        Field(
            description=(
                "List of approved backlog items from backlog_primer_tool output. "
                "Each must have: priority, requirement, value_driver, justification, estimated_effort."
            )
        ),
    ]


async def save_backlog_tool(
    save_input: SaveBacklogInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Save approved backlog items to the DATABASE as UserStory records.

    This tool persists the approved backlog items directly to the UserStory table
    so they are available for Sprint Planning and Roadmap creation.

    Use this tool when:
    - User approves the backlog in BACKLOG_REVIEW state
    """
    if not tool_context:
        return {
            "success": False,
            "error": "ToolContext required for session state storage.",
        }

    # Validate backlog items using BacklogItem schema
    validated_items: List[BacklogItem] = []
    validation_errors: List[str] = []

    for idx, item in enumerate(save_input.backlog_items):
        try:
            validated = BacklogItem.model_validate(item)
            validated_items.append(validated)
        except ValidationError as e:
            errors = [f"{err['loc'][0]}: {err['msg']}" for err in e.errors()]
            validation_errors.append(f"Item {idx + 1}: {'; '.join(errors)}")

    if validation_errors:
        return {
            "success": False,
            "error": f"Validation errors: {'; '.join(validation_errors)}",
            "valid_count": len(validated_items),
            "invalid_count": len(validation_errors),
        }

    # 1. Update Session State (Legacy/Fallback support)
    tool_context.state["approved_backlog"] = {
        "product_id": save_input.product_id,
        "items": [item.model_dump() for item in validated_items],
        "item_count": len(validated_items),
    }

    # 2. Persist to Database (New Logic)
    engine = get_engine()
    created_count = 0
    
    with Session(engine) as session:
        for item in validated_items:
            # Check for duplicates to prevent double-saving on retries
            # (Simple check: same title, same product, same status=TO_DO)
            existing = session.exec(
                select(UserStory)
                .where(UserStory.product_id == save_input.product_id)
                .where(UserStory.title == item.requirement)
                .where(UserStory.status == StoryStatus.TO_DO)
            ).first()

            if existing:
                continue

            # Create new UserStory
            # Mapping:
            # requirement -> title
            # priority -> rank (converted to string to ensure sortability? or just numeric string)
            # estimated_effort -> story_points (approximate mapping)
            
            # Map 'S', 'M', 'L', 'XL' (and legacy Low/Medium/High) to points
            points = None
            effort_str = str(item.estimated_effort).strip().upper()
            
            # T-Shirt Sizing from schema
            if effort_str == 'S': points = 1
            elif effort_str == 'M': points = 3
            elif effort_str == 'L': points = 5
            elif effort_str == 'XL': points = 8
            # Legacy/Fallback
            elif effort_str == 'LOW': points = 1
            elif effort_str == 'MEDIUM': points = 3
            elif effort_str == 'HIGH': points = 5
            elif effort_str.isdigit(): points = int(effort_str)

            new_story = UserStory(
                title=item.requirement,
                product_id=save_input.product_id,
                status=StoryStatus.TO_DO,
                rank=str(item.priority), # Storing priority as rank
                story_points=points,
                story_description=item.justification, # Using justification as initial description context
                acceptance_criteria=None # To be filled by UserStory Writer later
            )
            session.add(new_story)
            created_count += 1
        
        session.commit()

    print(f"\n\033[92m[Backlog Saved]\033[0m {created_count} new items persisted to DB (Total processed: {len(validated_items)})")

    return {
        "success": True,
        "product_id": save_input.product_id,
        "saved_count": created_count,
        "total_items": len(validated_items),
        "message": f"Backlog saved. {created_count} new stories created in database.",
        "next_phase": "roadmap", # Or "sprint_planning" if user prefers
    }


__all__ = ["SaveBacklogInput", "save_backlog_tool"]
