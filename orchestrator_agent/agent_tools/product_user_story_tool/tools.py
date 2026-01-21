# orchestrator_agent/agent_tools/product_user_story_tool/tools.py
"""
Tools for creating and persisting user stories from the orchestrator.
"""

from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Theme, UserStory, engine


# --- Schema for creating a single user story ---


class CreateStoryInput(BaseModel):
    """Input schema for create_user_story_tool."""

    product_id: Annotated[int, Field(description="The product ID to link the story to.")]
    feature_id: Annotated[int, Field(description="The feature ID to link the story to.")]
    title: Annotated[str, Field(description="The user story title (e.g., 'Add ingredient to pantry').")]
    description: Annotated[
        str,
        Field(description="The story description in 'As a... I want... So that...' format."),
    ]
    acceptance_criteria: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Bullet-point acceptance criteria. Optional.",
        ),
    ]
    story_points: Annotated[
        Optional[int],
        Field(default=None, description="Story point estimate. Optional."),
    ]


def create_user_story_tool(story_input: CreateStoryInput) -> Dict[str, Any]:
    """
    Persist a single user story to the database.

    Returns:
        Dict with success status, story_id if created, and message.
    """
    print(
        f"\n[Tool: create_user_story_tool] Creating story '{story_input.title}'..."
    )

    try:
        with Session(engine) as session:
            # Validate feature exists
            feature = session.get(Feature, story_input.feature_id)
            if not feature:
                print(f"   [DB] Feature {story_input.feature_id} not found.")
                return {
                    "success": False,
                    "error": f"Feature {story_input.feature_id} not found",
                }

            # Create the story
            story = UserStory(
                title=story_input.title,
                story_description=story_input.description,
                acceptance_criteria=story_input.acceptance_criteria,
                story_points=story_input.story_points,
                feature_id=story_input.feature_id,
                product_id=story_input.product_id,
            )
            session.add(story)
            session.commit()
            session.refresh(story)

            print(f"   [DB] Created story ID: {story.story_id}")
            return {
                "success": True,
                "story_id": story.story_id,
                "feature_id": story_input.feature_id,
                "product_id": story_input.product_id,
                "title": story_input.title,
                "message": f"Created user story '{story_input.title}' with ID {story.story_id}",
            }

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return {"success": False, "error": f"Database error: {str(e)}"}


# --- Schema for batch creation ---


class BatchCreateStoriesInput(BaseModel):
    """Input schema for batch story creation."""

    product_id: Annotated[int, Field(description="The product ID.")]
    stories: Annotated[
        List[Dict[str, Any]],
        Field(
            description=(
                "List of story dicts with keys: feature_id, title, description, "
                "acceptance_criteria (optional), story_points (optional)."
            )
        ),
    ]


def batch_create_user_stories_tool(
    batch_input: BatchCreateStoriesInput,
) -> Dict[str, Any]:
    """
    Persist multiple user stories at once.

    Returns:
        Dict with success status, created story IDs, and any errors.
    """
    print(
        f"\n[Tool: batch_create_user_stories_tool] Creating {len(batch_input.stories)} stories..."
    )

    created: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for story_data in batch_input.stories:
        result = create_user_story_tool(
            CreateStoryInput(
                product_id=batch_input.product_id,
                feature_id=story_data["feature_id"],
                title=story_data["title"],
                description=story_data["description"],
                acceptance_criteria=story_data.get("acceptance_criteria"),
                story_points=story_data.get("story_points"),
            )
        )

        if result["success"]:
            created.append(result)
        else:
            errors.append({"story": story_data, "error": result.get("error")})

    print(f"   [DB] Created {len(created)} stories, {len(errors)} errors.")
    return {
        "success": len(errors) == 0,
        "created_count": len(created),
        "created_stories": created,
        "errors": errors,
        "message": f"Created {len(created)} user stories. {len(errors)} failed.",
    }


# --- Tool for querying features (for the agent to know what's available) ---


class QueryFeaturesInput(BaseModel):
    """Input schema for querying features."""

    product_id: Annotated[int, Field(description="The product ID to query.")]


def query_features_for_stories(
    query_input: QueryFeaturesInput,
) -> Dict[str, Any]:
    """
    Query all features for a product, organized by theme/epic.
    Used by the orchestrator to provide context to the user story agent.

    Returns:
        Dict with hierarchical structure of themes -> epics -> features.
    """
    print(
        f"\n[Tool: query_features_for_stories] Querying product {query_input.product_id}..."
    )

    try:
        with Session(engine) as session:
            product = session.get(Product, query_input.product_id)
            if not product:
                return {
                    "success": False,
                    "error": f"Product {query_input.product_id} not found",
                }

            themes = session.exec(
                select(Theme).where(Theme.product_id == query_input.product_id)
            ).all()

            features_list: List[Dict[str, Any]] = []
            structure: List[Dict[str, Any]] = []

            for theme in themes:
                # Collect all features in this theme for sibling_features
                theme_all_features: List[str] = []
                
                theme_data: Dict[str, Any] = {
                    "theme_id": theme.theme_id,
                    "theme_title": theme.title,
                    "time_frame": theme.time_frame.value if theme.time_frame else None,
                    "justification": theme.description,  # Theme.description = justification
                    "epics": [],
                }

                epics = session.exec(
                    select(Epic).where(Epic.theme_id == theme.theme_id)
                ).all()
                
                # First pass: collect all feature titles in this theme
                for epic in epics:
                    epic_features = session.exec(
                        select(Feature).where(Feature.epic_id == epic.epic_id)
                    ).all()
                    for f in epic_features:
                        theme_all_features.append(f.title)

                for epic in epics:
                    epic_data: Dict[str, Any] = {
                        "epic_id": epic.epic_id,
                        "epic_title": epic.title,
                        "features": [],
                    }

                    features = session.exec(
                        select(Feature).where(Feature.epic_id == epic.epic_id)
                    ).all()

                    for feature in features:
                        # Count existing stories for this feature
                        existing_stories = session.exec(
                            select(UserStory).where(
                                UserStory.feature_id == feature.feature_id
                            )
                        ).all()
                        
                        # Sibling features = all features in this theme except current
                        sibling_features = [f for f in theme_all_features if f != feature.title]

                        feature_info: Dict[str, Any] = {
                            "feature_id": feature.feature_id,
                            "feature_title": feature.title,
                            "existing_stories_count": len(existing_stories),
                            # Roadmap context for story pipeline
                            "time_frame": theme.time_frame.value if theme.time_frame else None,
                            "theme_justification": theme.description,  # Theme.description = justification
                            "sibling_features": sibling_features,
                        }
                        epic_data["features"].append(feature_info)
                        features_list.append(
                            {
                                **feature_info,
                                "theme": theme.title,
                                "epic": epic.title,
                            }
                        )

                    theme_data["epics"].append(epic_data)

                structure.append(theme_data)

            print(f"   [DB] Found {len(features_list)} features.")
            return {
                "success": True,
                "product_id": query_input.product_id,
                "product_name": product.name,
                "features_flat": features_list,
                "structure": structure,
                "total_features": len(features_list),
                "message": f"Found {len(features_list)} features for '{product.name}'",
            }

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return {"success": False, "error": f"Database error: {str(e)}"}
