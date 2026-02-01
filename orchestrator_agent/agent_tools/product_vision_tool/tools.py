# orchestrator_agent/agent_tools/product_vision_tool/tools.py
"""
product_tools.py
"""

from datetime import datetime
from typing import Annotated, Any, Dict

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from agile_sqlmodel import Product, get_engine


# --- Tool for SAVING the vision ---


class SaveVisionInput(BaseModel):
    """Schema for the 'save_vision' tool."""

    project_name: Annotated[str, Field(description="Unique name.")]
    product_vision_statement: Annotated[str, Field(description="Vision text.")]


def save_vision_tool(
    vision_input: SaveVisionInput, tool_context: ToolContext
) -> Dict[str, Any]:
    """
    COMMITS the finalized Product Vision to the Business Database.
    """
    print(
        f"\n[Tool: save_vision_tool] Saving '{vision_input.project_name}'..."
    )

    try:
        with Session(get_engine()) as session:
            statement = select(Product).where(
                Product.name == vision_input.project_name
            )
            existing_project = session.exec(statement).first()
            p_id = None

            if existing_project:
                print(f"   [DB] Updating ID: {existing_project.product_id}")
                existing_project.vision = vision_input.product_vision_statement
                session.add(existing_project)
                action = "Updated"
                p_id = existing_project.product_id
            else:
                print("   [DB] Creating new record.")
                new_project = Product(
                    name=vision_input.project_name,
                    vision=vision_input.product_vision_statement,
                    roadmap=None,
                )
                session.add(new_project)
                session.commit()
                session.refresh(new_project)
                action = "Created"
                p_id = new_project.product_id

            if existing_project:
                session.commit()

            # Using tool_context here is fine because we actually use it
            tool_context.state["current_project_name"] = (
                vision_input.project_name
            )

            return {
                "success": True,
                "product_id": p_id,
                "message": f"SUCCESS: {action} project '{vision_input.project_name}'.",
                "project_name": vision_input.project_name,
            }

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return {"success": False, "error": f"Database Error: {str(e)}"}


# --- Tool for READING the vision ---


class ReadVisionInput(BaseModel):
    """Input schema for reading vision."""

    project_name: Annotated[str, Field(description="Name of the project.")]


# FIX: Removed tool_context argument entirely because it is unused.
def read_vision_tool(vision_input: ReadVisionInput) -> str:
    """
    Reads the Product Vision from the Business Database.
    """
    print(
        f"\n[Tool: read_vision_tool] Querying '{vision_input.project_name}'..."
    )

    with Session(get_engine()) as session:
        statement = select(Product).where(
            Product.name == vision_input.project_name
        )
        project = session.exec(statement).first()

        if project and project.vision:
            print("   [DB] Found vision.")
            return project.vision

        if project:
            print("   [DB] Project exists but has no vision.")
            return "Project exists but vision is empty."

        print("   [DB] Project not found.")
        return f"Error: Project '{vision_input.project_name}' not found."


# --- Utility Tools ---


# FIX: Removed tool_context argument.
def get_current_time_tool() -> Dict[str, Any]:
    """Returns the current time."""
    try:
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {"status": "success", "current_time": time_str}
    except ValueError as e:
        return {"status": "error", "error_message": str(e)}
