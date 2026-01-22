# orchestrator_agent/agent_tools/product_user_story_tool/tools.py
"""
Tools for creating and persisting user stories from the orchestrator.
"""

from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import func
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

            # 1. Fetch all Themes
            themes = session.exec(
                select(Theme).where(Theme.product_id == query_input.product_id)
            ).all()
            theme_ids = [t.theme_id for t in themes]

            # 2. Fetch all Epics for these themes
            epics = []
            if theme_ids:
                epics = session.exec(
                    select(Epic).where(Epic.theme_id.in_(theme_ids))
                ).all()

            epic_ids = [e.epic_id for e in epics]
            epics_by_theme: Dict[int, List[Epic]] = {tid: [] for tid in theme_ids}
            epic_to_theme: Dict[int, int] = {}
            for epic in epics:
                epics_by_theme[epic.theme_id].append(epic)
                epic_to_theme[epic.epic_id] = epic.theme_id

            # 3. Fetch all Features for these epics
            features = []
            if epic_ids:
                features = session.exec(
                    select(Feature).where(Feature.epic_id.in_(epic_ids))
                ).all()

            feature_ids = [f.feature_id for f in features]
            features_by_epic: Dict[int, List[Feature]] = {eid: [] for eid in epic_ids}
            features_by_theme: Dict[int, List[str]] = {tid: [] for tid in theme_ids}

            for feature in features:
                features_by_epic[feature.epic_id].append(feature)
                # Map feature to theme via epic
                theme_id = epic_to_theme.get(feature.epic_id)
                if theme_id is not None:
                    features_by_theme[theme_id].append(feature.title)

            # 4. Fetch Story Counts grouped by feature
            story_counts: Dict[int, int] = {}
            if feature_ids:
                story_counts_query = (
                    select(UserStory.feature_id, func.count(UserStory.story_id))
                    .where(UserStory.feature_id.in_(feature_ids))
                    .group_by(UserStory.feature_id)
                )
                results = session.exec(story_counts_query).all()
                story_counts = {row[0]: row[1] for row in results}

            # 5. Assemble structure
            features_list: List[Dict[str, Any]] = []
            structure: List[Dict[str, Any]] = []

            for theme in themes:
                theme_data: Dict[str, Any] = {
                    "theme_id": theme.theme_id,
                    "theme_title": theme.title,
                    "time_frame": theme.time_frame.value if theme.time_frame else None,
                    "justification": theme.description,
                    "epics": [],
                }

                # Get all feature titles in this theme for sibling comparison
                theme_all_features = features_by_theme.get(theme.theme_id, [])

                for epic in epics_by_theme.get(theme.theme_id, []):
                    epic_data: Dict[str, Any] = {
                        "epic_id": epic.epic_id,
                        "epic_title": epic.title,
                        "features": [],
                    }

                    for feature in features_by_epic.get(epic.epic_id, []):
                        count = story_counts.get(feature.feature_id, 0)
                        
                        # Sibling features = all features in this theme except current
                        sibling_features = [f for f in theme_all_features if f != feature.title]

                        feature_info: Dict[str, Any] = {
                            "feature_id": feature.feature_id,
                            "feature_title": feature.title,
                            "existing_stories_count": count,
                            "time_frame": theme.time_frame.value if theme.time_frame else None,
                            "theme_justification": theme.description,
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
