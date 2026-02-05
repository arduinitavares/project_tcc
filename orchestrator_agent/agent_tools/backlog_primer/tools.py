"""Tools for backlog_primer agent."""

from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError

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
    Save approved backlog items to session state.

    This tool stores the approved backlog in session state for later use
    in roadmap creation. It does NOT persist to database.

    Use this tool when:
    - User approves the backlog in BACKLOG_REVIEW state
    - You need to save the backlog before transitioning to roadmap creation
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

    # Store in session state (serialize to dicts for JSON compatibility)
    tool_context.state["approved_backlog"] = {
        "product_id": save_input.product_id,
        "items": [item.model_dump() for item in validated_items],
        "item_count": len(validated_items),
    }

    print(f"\n\033[92m[Backlog Saved]\033[0m {len(validated_items)} items stored in session state")

    return {
        "success": True,
        "product_id": save_input.product_id,
        "saved_count": len(validated_items),
        "message": f"Backlog with {len(validated_items)} items saved to session state. Ready for roadmap creation.",
        "next_phase": "roadmap",
    }


__all__ = ["SaveBacklogInput", "save_backlog_tool"]
