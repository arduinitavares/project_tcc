# tools/db_tools.py

"""
Database persistence tools for agents to call.
These functions are designed to be invoked by Claude as tool calls.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlmodel import Session, select

from agile_sqlmodel import (
    Epic,
    Feature,
    Product,
    Task,
    Theme,
    UserStory,
    engine,
)


class CreateOrGetProductInput(BaseModel):
    """Input schema for create_or_get_product tool."""

    product_name: str
    vision: Optional[str]
    description: Optional[str]


def create_or_get_product(params: CreateOrGetProductInput) -> Dict[str, Any]:
    """
    Agent tool: Create a product or update its vision.

    Args:
        params: Input data for creating or getting a product.

    Returns:
        Dict with product_id and status
    """
    with Session(engine) as session:
        # Try to find existing product
        product = session.exec(
            select(Product).where(Product.name == params.product_name)
        ).first()

        if not product:
            product = Product(
                name=params.product_name,
                vision=params.vision,
                description=params.description,
            )
            session.add(product)
            session.commit()
            session.refresh(product)
            return {
                "success": True,
                "product_id": product.product_id,
                "action": "created",
                "message": (
                    f"Created product '{params.product_name}' "
                    f"with ID {product.product_id}"
                ),
            }

        if params.vision is not None:
            product.vision = params.vision
        if params.description is not None:
            product.description = params.description
        session.add(product)
        session.commit()
        session.refresh(product)
        return {
            "success": True,
            "product_id": product.product_id,
            "action": "updated",
            "message": (
                f"Updated product '{params.product_name}' "
                f"(ID {product.product_id})"
            ),
        }


def persist_roadmap(
    product_id: int, roadmap_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Agent tool: Parse roadmap and create Theme/Epic/Feature hierarchy.

    Args:
        product_id: The product to attach roadmap to
        roadmap_items: List of dicts with structure. (See docstring in editor)

    Returns:
        Dict with created IDs and status
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product {product_id} not found",
            }

        created: Dict[str, List[Dict[str, Any]]] = {
            "themes": [],
            "epics": [],
            "features": [],
        }

        for item in roadmap_items:
            # Create Theme
            theme = Theme(
                title=(
                    f"{item.get('quarter', '')} - "
                    f"{item.get('theme_title', 'Unnamed')}"
                ),
                description=item.get("theme_description", ""),
                product_id=product_id,
            )
            session.add(theme)
            session.flush()

            if theme.theme_id is None:
                raise RuntimeError(
                    f"Failed to create Theme '{theme.title}', ID is None after flush."
                )
            created["themes"].append(
                {"id": theme.theme_id, "title": theme.title}
            )

            # Create Epics under this Theme
            for epic_data in item.get("epics", []):
                epic = Epic(
                    title=epic_data.get("epic_title", "Unnamed Epic"),
                    summary=epic_data.get("epic_summary", ""),
                    theme_id=theme.theme_id,
                )
                session.add(epic)
                session.flush()

                if epic.epic_id is None:
                    raise RuntimeError(
                        f"Failed to create Epic '{epic.title}', ID is None after flush."
                    )
                created["epics"].append(
                    {"id": epic.epic_id, "title": epic.title}
                )

                # Create Features under this Epic
                for feature_data in epic_data.get("features", []):
                    feature = Feature(
                        title=feature_data.get("title", "Unnamed Feature"),
                        description=feature_data.get("description", ""),
                        epic_id=epic.epic_id,
                    )
                    session.add(feature)
                    session.flush()

                    if feature.feature_id is None:
                        raise RuntimeError(
                            "Failed to create Feature, ID is None after flush."
                        )
                    # Fix for Pylance (reportUnknownVariableType)
                    feature_dict: Dict[str, Any] = {
                        "id": feature.feature_id,
                        "title": feature.title,
                    }
                    created["features"].append(feature_dict)

        session.commit()

        return {
            "success": True,
            "product_id": product_id,
            "created": created,
            "message": (
                f"Created {len(created['themes'])} themes, "
                f"{len(created['epics'])} epics, "
                f"{len(created['features'])} features"
            ),
        }


class CreateUserStoryInput(BaseModel):
    """Input schema for create_user_story tool."""

    product_id: int
    feature_id: int
    title: str
    description: str
    acceptance_criteria: Optional[str]
    story_points: Optional[int]


def create_user_story(params: CreateUserStoryInput) -> Dict[str, Any]:
    """
    Agent tool: Create a user story under a feature.

    Args:
        params: Input data for creating a user story.

    Returns:
        Dict with story_id and status
    """
    with Session(engine) as session:
        feature = session.get(Feature, params.feature_id)
        if not feature:
            return {
                "success": False,
                "error": f"Feature {params.feature_id} not found",
            }

        story = UserStory(
            title=params.title,
            story_description=params.description,
            acceptance_criteria=params.acceptance_criteria,
            story_points=params.story_points,
            feature_id=params.feature_id,
            product_id=params.product_id,
        )
        session.add(story)
        session.commit()
        session.refresh(story)

        return {
            "success": True,
            "story_id": story.story_id,
            "feature_id": params.feature_id,
            "product_id": params.product_id,
            "message": (
                f"Created user story '{params.title}' with ID {story.story_id}"
            ),
        }


class CreateTaskInput(BaseModel):
    """Input schema for create_task tool."""

    story_id: int
    title: str
    description: Optional[str]


def create_task(params: CreateTaskInput) -> Dict[str, Any]:
    """
    Agent tool: Create a task under a user story.

    Args:
        params: Input data for creating a task.

    Returns:
        Dict with task_id and status
    """
    with Session(engine) as session:
        story = session.get(UserStory, params.story_id)
        if not story:
            return {
                "success": False,
                "error": f"User story {params.story_id} not found",
            }

        # Fix for Pylance (reportCallIssue):
        # The 'Task' model only has a required 'description' field.
        # We combine the 'title' and optional 'description' from this
        # function to satisfy the model's requirement.
        task_description = params.title
        if params.description is not None:
            task_description = f"{params.title}\n\n{params.description}"

        task = Task(description=task_description, story_id=params.story_id)
        session.add(task)
        session.commit()
        session.refresh(task)

        return {
            "success": True,
            "task_id": task.task_id,
            "story_id": params.story_id,
            "message": f"Created task '{params.title}' with ID {task.task_id}",
        }


def query_product_structure(product_id: int) -> Dict[str, Any]:
    """
    Agent tool: Query the full hierarchy of a product (for verification).

    Returns the entire Theme -> Epic -> Feature -> Story structure.
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product {product_id} not found",
            }

        # 1. Fetch all themes
        themes = session.exec(
            select(Theme).where(Theme.product_id == product_id)
        ).all()
        theme_ids = [t.theme_id for t in themes if t.theme_id is not None]

        # 2. Fetch all epics
        epics: List[Epic] = []
        if theme_ids:
            epics = session.exec(
                select(Epic).where(Epic.theme_id.in_(theme_ids))
            ).all()
        epic_ids = [e.epic_id for e in epics if e.epic_id is not None]

        # 3. Fetch all features
        features: List[Feature] = []
        if epic_ids:
            features = session.exec(
                select(Feature).where(Feature.epic_id.in_(epic_ids))
            ).all()
        feature_ids = [f.feature_id for f in features if f.feature_id is not None]

        # 4. Fetch all stories
        stories: List[UserStory] = []
        if feature_ids:
            stories = session.exec(
                select(UserStory).where(UserStory.feature_id.in_(feature_ids))
            ).all()

        # 5. Build lookup maps
        # Map: theme_id -> [epics]
        epics_by_theme: Dict[int, List[Epic]] = {tid: [] for tid in theme_ids}
        for epic in epics:
            if epic.theme_id in epics_by_theme:
                epics_by_theme[epic.theme_id].append(epic)

        # Map: epic_id -> [features]
        features_by_epic: Dict[int, List[Feature]] = {eid: [] for eid in epic_ids}
        for feature in features:
            if feature.epic_id in features_by_epic:
                features_by_epic[feature.epic_id].append(feature)

        # Map: feature_id -> [stories]
        stories_by_feature: Dict[int, List[UserStory]] = {
            fid: [] for fid in feature_ids
        }
        for story in stories:
            if story.feature_id is not None and story.feature_id in stories_by_feature:
                stories_by_feature[story.feature_id].append(story)

        # 6. Assemble structure
        # Fix for Pylance (reportUnknownVariableType)
        structure: Dict[str, Any] = {
            "product": {
                "id": product.product_id,
                "name": product.name,
                "vision": product.vision,
            },
            "themes": [],
        }

        for theme in themes:
            # Fix for Pylance (reportUnknownVariableType)
            theme_data: Dict[str, Any] = {
                "id": theme.theme_id,
                "title": theme.title,
                "epics": [],
            }

            theme_epics = epics_by_theme.get(theme.theme_id, [])

            for epic in theme_epics:
                # Fix for Pylance (reportUnknownVariableType)
                epic_data: Dict[str, Any] = {
                    "id": epic.epic_id,
                    "title": epic.title,
                    "features": [],
                }

                epic_features = features_by_epic.get(epic.epic_id, [])

                for feature in epic_features:
                    # Fix for Pylance (reportUnknownVariableType)
                    feature_data: Dict[str, Any] = {
                        "id": feature.feature_id,
                        "title": feature.title,
                        "stories": [],
                    }

                    feature_stories = stories_by_feature.get(
                        feature.feature_id, []
                    )

                    for story in feature_stories:
                        feature_data["stories"].append(
                            {
                                "id": story.story_id,
                                "title": story.title,
                                "description": story.story_description,
                                "points": story.story_points,
                            }
                        )

                    epic_data["features"].append(feature_data)

                theme_data["epics"].append(epic_data)

            structure["themes"].append(theme_data)

        return {"success": True, "structure": structure}


def get_story_details(story_id: int) -> Dict[str, Any]:
    """
    Agent tool: Fetch details for a specific story by its ID.

    Args:
        story_id: The ID of the story to fetch

    Returns:
        Dict with story details or error message
    """
    with Session(engine) as session:
        story = session.get(UserStory, story_id)
        
        if not story:
            return {
                "success": False,
                "story_id": story_id,
                "message": f"Story with ID {story_id} not found."
            }
        
        return {
            "success": True,
            "story_id": story.story_id,
            "title": story.title,
            "description": story.story_description,
            "acceptance_criteria": story.acceptance_criteria,
            "status": story.status.value if hasattr(story.status, "value") else story.status,
            "story_points": story.story_points,
            "rank": story.rank,
            "feature_id": story.feature_id,
            "product_id": story.product_id,
            "created_at": str(story.created_at),
            "updated_at": str(story.updated_at),
        }

