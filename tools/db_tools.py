# tools/db_tools.py

"""
Database persistence tools for agents to call.
These functions are designed to be invoked by Claude as tool calls.
"""

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Task, Theme, UserStory, engine


def create_or_get_product(
    product_name: str,
    vision: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Agent tool: Create a product or update its vision.

    Args:
        product_name: Name of the product
        vision: Product vision statement (optional)
        description: Product description (optional)

    Returns:
        Dict with product_id and status
    """
    with Session(engine) as session:
        # Try to find existing product
        product = session.exec(
            select(Product).where(Product.name == product_name)
        ).first()

        if not product:
            product = Product(
                name=product_name,
                vision=vision,
                description=description,
            )
            session.add(product)
            session.commit()
            session.refresh(product)
            return {
                "success": True,
                "product_id": product.product_id,
                "action": "created",
                "message": (
                    f"Created product '{product_name}' " f"with ID {product.product_id}"
                ),
            }

        if vision:
            product.vision = vision
        if description:
            product.description = description
        session.add(product)
        session.commit()
        session.refresh(product)
        return {
            "success": True,
            "product_id": product.product_id,
            "action": "updated",
            "message": (
                f"Updated product '{product_name}' " f"(ID {product.product_id})"
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
            return {"success": False, "error": f"Product {product_id} not found"}

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
            session.commit()
            session.refresh(theme)

            if theme.theme_id is None:
                raise RuntimeError(
                    f"Failed to create Theme '{theme.title}', ID is None after commit."
                )
            created["themes"].append({"id": theme.theme_id, "title": theme.title})

            # Create Epics under this Theme
            for epic_data in item.get("epics", []):
                epic = Epic(
                    title=epic_data.get("epic_title", "Unnamed Epic"),
                    summary=epic_data.get("epic_summary", ""),
                    theme_id=theme.theme_id,
                )
                session.add(epic)
                session.commit()
                session.refresh(epic)

                if epic.epic_id is None:
                    raise RuntimeError(
                        f"Failed to create Epic '{epic.title}', ID is None after commit."
                    )
                created["epics"].append({"id": epic.epic_id, "title": epic.title})

                # Create Features under this Epic
                for feature_data in epic_data.get("features", []):
                    feature = Feature(
                        title=feature_data.get("title", "Unnamed Feature"),
                        description=feature_data.get("description", ""),
                        epic_id=epic.epic_id,
                    )
                    session.add(feature)
                    session.commit()
                    session.refresh(feature)

                    if feature.feature_id is None:
                        raise RuntimeError(
                            "Failed to create Feature, ID is None after commit."
                        )
                    # Fix for Pylance (reportUnknownVariableType)
                    feature_dict: Dict[str, Any] = {
                        "id": feature.feature_id,
                        "title": feature.title,
                    }
                    created["features"].append(feature_dict)

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


def create_user_story(  # pylint: disable=too-many-arguments
    product_id: int,
    feature_id: int,
    title: str,
    description: str,
    acceptance_criteria: Optional[str] = None,
    story_points: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Agent tool: Create a user story under a feature.

    Args:
        product_id: The product this story belongs to
        feature_id: The feature this story belongs to
        title: Story title
        description: Story description (typically "As a... I want... So that...")
        acceptance_criteria: Definition of Done/acceptance criteria
        story_points: Story point estimate (Fibonacci scale)

    Returns:
        Dict with story_id and status
    """
    with Session(engine) as session:
        feature = session.get(Feature, feature_id)
        if not feature:
            return {"success": False, "error": f"Feature {feature_id} not found"}

        story = UserStory(
            title=title,
            story_description=description,
            acceptance_criteria=acceptance_criteria,
            story_points=story_points,
            feature_id=feature_id,
            product_id=product_id,
        )
        session.add(story)
        session.commit()
        session.refresh(story)

        return {
            "success": True,
            "story_id": story.story_id,
            "feature_id": feature_id,
            "product_id": product_id,
            "message": (f"Created user story '{title}' with ID {story.story_id}"),
        }


def create_task(
    story_id: int, title: str, description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Agent tool: Create a task under a user story.

    Args:
        story_id: The user story this task belongs to
        title: Task title
        description: Task description

    Returns:
        Dict with task_id and status
    """
    with Session(engine) as session:
        story = session.get(UserStory, story_id)
        if not story:
            return {"success": False, "error": f"User story {story_id} not found"}

        # Fix for Pylance (reportCallIssue):
        # The 'Task' model only has a required 'description' field.
        # We combine the 'title' and optional 'description' from this
        # function to satisfy the model's requirement.
        task_description = title
        if description:
            task_description = f"{title}\n\n{description}"

        task = Task(description=task_description, story_id=story_id)
        session.add(task)
        session.commit()
        session.refresh(task)

        return {
            "success": True,
            "task_id": task.task_id,
            "story_id": story_id,
            "message": f"Created task '{title}' with ID {task.task_id}",
        }


def query_product_structure(product_id: int) -> Dict[str, Any]:
    """
    Agent tool: Query the full hierarchy of a product (for verification).

    Returns the entire Theme -> Epic -> Feature -> Story structure.
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {"success": False, "error": f"Product {product_id} not found"}

        themes = session.exec(select(Theme).where(Theme.product_id == product_id)).all()

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

            epics = session.exec(
                select(Epic).where(Epic.theme_id == theme.theme_id)
            ).all()

            for epic in epics:
                # Fix for Pylance (reportUnknownVariableType)
                epic_data: Dict[str, Any] = {
                    "id": epic.epic_id,
                    "title": epic.title,
                    "features": [],
                }

                features = session.exec(
                    select(Feature).where(Feature.epic_id == epic.epic_id)
                ).all()

                for feature in features:
                    # Fix for Pylance (reportUnknownVariableType)
                    feature_data: Dict[str, Any] = {
                        "id": feature.feature_id,
                        "title": feature.title,
                        "stories": [],
                    }

                    stories = session.exec(
                        select(UserStory).where(
                            UserStory.feature_id == feature.feature_id
                        )
                    ).all()

                    for story in stories:
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
