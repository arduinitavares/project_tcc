# orchestrator_agent/agent_tools/product_vision_tool/tools.py
"""
product_tools.py
"""

from typing import Annotated, Any, Dict, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from agile_sqlmodel import Product, get_engine


# --- Tool for SAVING the vision ---


class SaveVisionInput(BaseModel):
    """Schema for the 'save_vision' tool."""

    product_id: Annotated[Optional[int], Field(description="ID of the project to update. If None, creates a NEW project.")] = None
    project_name: Annotated[str, Field(description="Unique name of the project.")]
    product_vision_statement: Annotated[str, Field(description="Finalized vision text.")]


def save_vision_tool(
    vision_input: SaveVisionInput, tool_context: ToolContext
) -> Dict[str, Any]:
    """
    COMMITS the finalized Product Vision to the Business Database.
    Creates a NEW project if product_id is None, otherwise updates EXISTING.
    """
    print(
        f"\n[Tool: save_vision_tool] Processing '{vision_input.project_name}' (ID: {vision_input.product_id})..."
    )

    try:
        with Session(get_engine()) as session:
            p_id = vision_input.product_id

            active_record: Optional[Product] = None

            if p_id is None:
                # Check for existing project by name to prevent duplicates
                statement = select(Product).where(Product.name == vision_input.project_name)
                existing_by_name = session.exec(statement).first()

                if existing_by_name:
                    # Fallback to UPDATE mode using the found ID
                    p_id = existing_by_name.product_id
                    print(
                        f"   [DB] Found existing project by name '{vision_input.project_name}' (ID: {p_id}). Updating."
                    )
                    existing_by_name.vision = vision_input.product_vision_statement
                    session.add(existing_by_name)
                    session.commit()
                    session.refresh(existing_by_name)
                    active_record = existing_by_name
                    roadmap_content = existing_by_name.roadmap
                else:
                    # CREATE MODE
                    print(f"   [DB] Creating NEW project: '{vision_input.project_name}'")
                    new_project = Product(
                        name=vision_input.project_name,
                        vision=vision_input.product_vision_statement,
                    )
                    session.add(new_project)
                    session.commit()
                    session.refresh(new_project)
                    p_id = new_project.product_id
                    active_record = new_project
                    roadmap_content = new_project.roadmap
                    print(f"   [DB] Created with ID: {p_id}")
            else:
                # UPDATE MODE
                existing_project = session.get(Product, p_id)
                if not existing_project:
                    return {"success": False, "error": f"Product with ID {p_id} not found. Pass product_id=None to create a new project."}
                
                print(f"   [DB] Updating ID: {p_id}")
                existing_project.vision = vision_input.product_vision_statement
                existing_project.name = vision_input.project_name # Allow renaming
                session.add(existing_project)
                session.commit()
                active_record = existing_project
                roadmap_content = existing_project.roadmap

            # Update the context state so subsequent tools know the active project
            tool_context.state["current_project_name"] = (
                vision_input.project_name
            )
            # Also set it as the active selection.
            # Simplified Update: We only set what we know. We do not attempt to preserve 'structure' 
            # or other fields from potentially non-existent previous state, as this caused crashes.
            tool_context.state["active_project"] = {
                "product_id": p_id,
                "name": vision_input.project_name,
                "description": active_record.description if active_record else None,
                "vision": vision_input.product_vision_statement,
                "roadmap": roadmap_content,
                "technical_spec": active_record.technical_spec if active_record else None,
                "compiled_authority_json": active_record.compiled_authority_json if active_record else None,
                "spec_file_path": active_record.spec_file_path if active_record else None,
                "spec_loaded_at": (
                    active_record.spec_loaded_at.isoformat()
                    if active_record and active_record.spec_loaded_at
                    else None
                ),
                "latest_spec_version_id": None,
                "structure": {
                    "themes": 0,
                    "epics": 0,
                    "features": 0,
                    "user_stories": 0,
                },
            }

            return {
                "success": True,
                "product_id": p_id,
                "message": f"SUCCESS: Saved project '{vision_input.project_name}' vision (ID: {p_id}).",
                "project_name": vision_input.project_name,
            }

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return {"success": False, "error": f"Database Error: {str(e)}"}

