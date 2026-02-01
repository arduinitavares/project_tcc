# orchestrator_agent/agent_tools/product_roadmap_agent/tools.py
"""
Tools for saving and managing product roadmaps.
"""

from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Theme, TimeFrame, get_engine


# --- Schema for structured roadmap themes ---


class RoadmapThemeInput(BaseModel):
    """A single theme from the roadmap draft."""

    theme_name: str
    key_features: List[str]
    justification: Optional[str] = None
    time_frame: Optional[str] = None


# --- Tool for SAVING the roadmap ---


class SaveRoadmapInput(BaseModel):
    """Schema for the 'save_roadmap' tool."""

    project_name: Annotated[str, Field(description="Unique project name.")]
    roadmap_text: Annotated[
        str, Field(description="The formatted roadmap text to save.")
    ]
    roadmap_structure: Annotated[
        Optional[List[RoadmapThemeInput]],
        Field(
            default=None,
            description=(
                "Optional: The structured roadmap_draft from the agent. "
                "If provided, Theme/Epic/Feature records will be created."
            ),
        ),
    ]


def _parse_time_frame(time_frame_str: Optional[str]) -> Optional[TimeFrame]:
    """Parse time frame string to TimeFrame enum."""
    if not time_frame_str:
        return None
    normalized = time_frame_str.strip().lower()
    if normalized == "now":
        return TimeFrame.NOW
    elif normalized == "next":
        return TimeFrame.NEXT
    elif normalized == "later":
        return TimeFrame.LATER
    return None


def _create_structure_from_themes(
    session: Session,
    product_id: int,
    themes: List[RoadmapThemeInput],
) -> Dict[str, Any]:
    """
    Create Theme/Epic/Feature hierarchy from roadmap themes.
    
    Strategy: Each theme becomes a Theme, and each key_feature becomes
    a Feature under a single Epic per theme.
    """
    created: Dict[str, List[Dict[str, Any]]] = {
        "themes": [],
        "epics": [],
        "features": [],
    }

    for theme_input in themes:
        # Parse time_frame to enum
        time_frame_enum = _parse_time_frame(theme_input.time_frame)
        time_frame_str = theme_input.time_frame or ""
        
        # Create Theme title (keep human-readable format for display)
        theme_title = (
            f"{time_frame_str} - {theme_input.theme_name}".strip(" -")
            if time_frame_str
            else theme_input.theme_name
        )
        
        theme = Theme(
            title=theme_title,
            description=theme_input.justification or "",
            time_frame=time_frame_enum,  # NEW: Store as enum
            product_id=product_id,
        )
        session.add(theme)
        session.commit()
        session.refresh(theme)
        
        if theme.theme_id is None:
            raise ValueError(f"Failed to create theme '{theme_title}' in database")

        created["themes"].append({"id": theme.theme_id, "title": theme.title})

        # Create a single Epic per theme (theme_name as epic)
        epic = Epic(
            title=theme_input.theme_name,
            summary=theme_input.justification or "",
            theme_id=theme.theme_id,
        )
        session.add(epic)
        session.commit()
        session.refresh(epic)
        
        if epic.epic_id is None:
            raise ValueError(f"Failed to create epic '{theme_input.theme_name}' in database")

        created["epics"].append({"id": epic.epic_id, "title": epic.title})

        # Create Features from key_features
        for feature_name in theme_input.key_features:
            feature = Feature(
                title=feature_name,
                description="",
                epic_id=epic.epic_id,
            )
            session.add(feature)
            session.commit()
            session.refresh(feature)
            
            if feature.feature_id is None:
                raise ValueError(f"Failed to create feature '{feature_name}' in database")

            created["features"].append({
                "id": feature.feature_id,
                "title": feature.title,
            })

    return created


def save_roadmap_tool(
    roadmap_input: SaveRoadmapInput, tool_context: ToolContext
) -> str:
    """
    COMMITS the finalized Product Roadmap to the Business Database.
    Also creates Theme/Epic/Feature structure if roadmap_structure is provided.
    """
    print(
        f"\n[Tool: save_roadmap_tool] Saving roadmap for '{roadmap_input.project_name}'..."
    )

    try:
        with Session(get_engine()) as session:
            statement = select(Product).where(
                Product.name == roadmap_input.project_name
            )
            existing_project = session.exec(statement).first()

            if existing_project:
                if existing_project.product_id is None:
                    return f"ERROR: Product '{roadmap_input.project_name}' has no ID in database."
                
                print(f"   [DB] Updating ID: {existing_project.product_id}")
                existing_project.roadmap = roadmap_input.roadmap_text
                session.add(existing_project)
                session.commit()
                
                # Update tool context
                tool_context.state["current_roadmap"] = (
                    roadmap_input.roadmap_text
                )

                result_msg = f"SUCCESS: Updated roadmap for '{roadmap_input.project_name}'."
                
                # If structured roadmap provided, create Theme/Epic/Feature records
                if roadmap_input.roadmap_structure:
                    print("   [DB] Creating Theme/Epic/Feature structure...")
                    created = _create_structure_from_themes(
                        session,
                        existing_project.product_id,
                        roadmap_input.roadmap_structure,
                    )
                    result_msg += (
                        f" Created {len(created['themes'])} themes, "
                        f"{len(created['epics'])} epics, "
                        f"{len(created['features'])} features."
                    )
                    print(f"   [DB] {result_msg}")
                
                return result_msg
            else:
                print("   [DB] Project not found.")
                return (
                    f"ERROR: Project '{roadmap_input.project_name}' not found. "
                    "Please create a vision first."
                )

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return f"Database Error: {str(e)}"
