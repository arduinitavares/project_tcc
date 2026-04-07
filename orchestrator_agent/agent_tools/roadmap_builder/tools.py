"""Tools for the Roadmap Builder agent."""

from typing import Annotated, Any, Dict
import json
import time

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from models.core import Product
from models.db import get_engine
from models.enums import WorkflowEventType
from models.events import WorkflowEvent
from orchestrator_agent.agent_tools.roadmap_builder.schemes import RoadmapBuilderOutput


class SaveRoadmapToolInput(BaseModel):
    """Input schema for the save_roadmap_tool."""

    product_id: Annotated[
        int,
        Field(description="The ID of the product to update."),
    ]
    roadmap_data: Annotated[
        RoadmapBuilderOutput,
        Field(description="The comprehensive roadmap data to save."),
    ]


def save_roadmap_tool(
    input_data: SaveRoadmapToolInput,
    tool_context: ToolContext | None = None,
) -> Dict[str, Any]:
    """
    Saves the generated roadmap to the Product.roadmap field in the database.
    Input must be the full RoadmapBuilderOutput object.
    """
    engine = get_engine()
    start_ts = time.perf_counter()
    
    with Session(engine) as session:
        # Retrieve the product
        product = session.exec(
            select(Product).where(Product.product_id == input_data.product_id)
        ).first()

        if not product:
            return {
                "success": False,
                "error": f"Product with ID {input_data.product_id} not found.",
            }

        # Serialize the roadmap data to JSON
        # We save the whole output (releases + summary)
        roadmap_json = input_data.roadmap_data.model_dump_json()

        # Update the product
        product.roadmap = roadmap_json
        session.add(product)
        duration_seconds = None
        if tool_context and tool_context.state:
            duration_seconds = tool_context.state.get("roadmap_generation_duration")
        if duration_seconds is None:
            duration_seconds = round(time.perf_counter() - start_ts, 3)
        session_id = getattr(tool_context, "session_id", None) if tool_context else None
        metadata = json.dumps(
            {"releases_count": len(input_data.roadmap_data.roadmap_releases)}
        )
        session.add(
            WorkflowEvent(
                event_type=WorkflowEventType.ROADMAP_SAVED,
                product_id=input_data.product_id,
                session_id=session_id,
                duration_seconds=float(duration_seconds),
                event_metadata=metadata,
            )
        )
        session.commit()
        session.refresh(product)

        return {
            "success": True,
            "product_id": product.product_id,
            "message": "Roadmap saved successfully to Product.roadmap.",
            "releases_count": len(input_data.roadmap_data.roadmap_releases),
        }
