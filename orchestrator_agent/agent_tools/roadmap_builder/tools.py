"""Tools for the Roadmap Builder agent."""

from typing import Annotated, Any, Dict

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agile_sqlmodel import Product, get_engine
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
) -> Dict[str, Any]:
    """
    Saves the generated roadmap to the Product.roadmap field in the database.
    Input must be the full RoadmapBuilderOutput object.
    """
    engine = get_engine()
    
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
        session.commit()
        session.refresh(product)

        return {
            "success": True,
            "product_id": product.product_id,
            "message": "Roadmap saved successfully to Product.roadmap.",
            "releases_count": len(input_data.roadmap_data.roadmap_releases),
        }
