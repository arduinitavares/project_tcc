# orchestrator_agent/agent_tools/product_roadmap_agent/tools.py
"""
Tools for saving and managing product roadmaps.
"""

from typing import Annotated

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from agile_sqlmodel import Product, engine


# --- Tool for SAVING the roadmap ---


class SaveRoadmapInput(BaseModel):
    """Schema for the 'save_roadmap' tool."""

    project_name: Annotated[str, Field(description="Unique project name.")]
    roadmap_text: Annotated[
        str, Field(description="The formatted roadmap text to save.")
    ]


def save_roadmap_tool(
    roadmap_input: SaveRoadmapInput, tool_context: ToolContext
) -> str:
    """
    COMMITS the finalized Product Roadmap to the Business Database.
    """
    print(
        f"\n[Tool: save_roadmap_tool] Saving roadmap for '{roadmap_input.project_name}'..."
    )

    try:
        with Session(engine) as session:
            statement = select(Product).where(
                Product.name == roadmap_input.project_name
            )
            existing_project = session.exec(statement).first()

            if existing_project:
                print(f"   [DB] Updating ID: {existing_project.product_id}")
                existing_project.roadmap = roadmap_input.roadmap_text
                session.add(existing_project)
                session.commit()
                
                # Update tool context
                tool_context.state["current_roadmap"] = (
                    roadmap_input.roadmap_text
                )

                return f"SUCCESS: Updated roadmap for '{roadmap_input.project_name}'."
            else:
                print("   [DB] Project not found.")
                return (
                    f"ERROR: Project '{roadmap_input.project_name}' not found. "
                    "Please create a vision first."
                )

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return f"Database Error: {str(e)}"
