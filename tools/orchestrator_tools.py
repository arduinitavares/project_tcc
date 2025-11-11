"""
Read-only tools for the orchestrator agent to make decisions.
These tools help the orchestrator understand the current state of projects.
"""

from typing import Any, Dict, List

from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Theme, UserStory, engine


def count_projects() -> Dict[str, Any]:
    """
    Agent tool: Count total projects in the database.

    Returns:
        Dict with count and status
    """
    with Session(engine) as session:
        products = session.exec(select(Product)).all()
        return {
            "success": True,
            "count": len(products),
            "message": f"Found {len(products)} project(s) in the database",
        }


def list_projects() -> Dict[str, Any]:
    """
    Agent tool: List all projects with summary info.

    Returns:
        Dict with project list
    """
    with Session(engine) as session:
        products = session.exec(select(Product)).all()

        projects = []
        for product in products:
            # Count related items
            stories = session.exec(
                select(UserStory).where(UserStory.product_id == product.product_id)
            ).all()

            projects.append(
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "vision": product.vision if product.vision else "(No vision set)",
                    "roadmap": (
                        product.roadmap if product.roadmap else "(No roadmap set)"
                    ),
                    "user_stories_count": len(stories),
                }
            )

        return {
            "success": True,
            "count": len(projects),
            "projects": projects,
            "message": f"Listed {len(projects)} project(s)",
        }


def get_project_details(product_id: int) -> Dict[str, Any]:
    """
    Agent tool: Get detailed breakdown of a project.

    Args:
        product_id: The product ID to query

    Returns:
        Dict with full project structure including:
        - Product info (name, vision, roadmap)
        - Theme/Epic/Feature count
        - User stories with counts
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {"success": False, "error": f"Product {product_id} not found"}

        # Count hierarchical items
        themes = session.exec(select(Theme).where(Theme.product_id == product_id)).all()

        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()

        # Count epics and features via themes
        total_epics = 0
        total_features = 0
        for theme in themes:
            epics = session.exec(
                select(Epic).where(Epic.theme_id == theme.theme_id)
            ).all()
            total_epics += len(epics)

            for epic in epics:
                features = session.exec(
                    select(Feature).where(Feature.epic_id == epic.epic_id)
                ).all()
                total_features += len(features)

        return {
            "success": True,
            "product": {
                "id": product.product_id,
                "name": product.name,
                "vision": product.vision,
                "roadmap": product.roadmap,
            },
            "structure": {
                "themes": len(themes),
                "epics": total_epics,
                "features": total_features,
                "user_stories": len(stories),
            },
            "message": f"Project '{product.name}' has {len(themes)} theme(s), {total_epics} epic(s), {total_features} feature(s), {len(stories)} story(ies)",
        }


def get_project_by_name(project_name: str) -> Dict[str, Any]:
    """
    Agent tool: Find a project by name.

    Args:
        project_name: Name to search for

    Returns:
        Dict with product_id if found
    """
    with Session(engine) as session:
        product = session.exec(
            select(Product).where(Product.name == project_name)
        ).first()

        if not product:
            return {
                "success": False,
                "error": f"Project '{project_name}' not found",
            }

        return {
            "success": True,
            "product_id": product.product_id,
            "product_name": product.name,
            "message": f"Found project '{project_name}' with ID {product.product_id}",
        }
