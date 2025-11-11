"""
Test suite for orchestrator decision-making tools.
Tests the query tools used by the orchestrator agent.
"""

import pytest
from sqlmodel import Session, select

from tools.orchestrator_tools import (
    count_projects,
    get_project_by_name,
    get_project_details,
    list_projects,
)


def test_count_projects_empty(engine):
    """Test counting projects when database is empty."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    result = count_projects()

    assert result["success"] is True
    assert result["count"] == 0
    assert "0 project" in result["message"]


def test_count_projects_with_data(engine):
    """Test counting projects when products exist."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    import tools.db_tools as db_tools
    from tools.db_tools import create_or_get_product

    db_tools.engine = engine

    # Create 3 products
    create_or_get_product(product_name="Project A")
    create_or_get_product(product_name="Project B")
    create_or_get_product(product_name="Project C")

    result = count_projects()

    assert result["success"] is True
    assert result["count"] == 3
    assert "3 project" in result["message"]


def test_list_projects_empty(engine):
    """Test listing projects when database is empty."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    result = list_projects()

    assert result["success"] is True
    assert result["count"] == 0
    assert len(result["projects"]) == 0


def test_list_projects_with_data(engine):
    """Test listing projects with summary data."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    import tools.db_tools as db_tools
    from tools.db_tools import create_or_get_product, create_user_story, persist_roadmap

    db_tools.engine = engine

    # Create a product with structure
    prod_result = create_or_get_product(
        product_name="Test Project", vision="Test vision"
    )
    product_id = prod_result["product_id"]

    # Add roadmap
    roadmap = [
        {
            "quarter": "Q1",
            "theme_title": "Auth",
            "theme_description": "",
            "epics": [
                {
                    "epic_title": "Login",
                    "epic_summary": "",
                    "features": [
                        {"title": "Email Login", "description": ""},
                    ],
                }
            ],
        }
    ]
    roadmap_result = persist_roadmap(product_id, roadmap)
    feature_id = roadmap_result["created"]["features"][0]["id"]

    # Add a user story
    create_user_story(
        product_id=product_id,
        feature_id=feature_id,
        title="Login as user",
        description="As a user...",
    )

    # Now list projects
    result = list_projects()

    assert result["success"] is True
    assert result["count"] == 1
    assert len(result["projects"]) == 1

    project = result["projects"][0]
    assert project["product_id"] == product_id
    assert project["name"] == "Test Project"
    assert project["vision"] == "Test vision"
    assert project["user_stories_count"] == 1


def test_get_project_details_not_found(engine):
    """Test getting details for non-existent project."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    result = get_project_details(999)

    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_get_project_details_with_structure(engine):
    """Test getting detailed structure of a project."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    import tools.db_tools as db_tools
    from tools.db_tools import create_or_get_product, create_user_story, persist_roadmap

    db_tools.engine = engine

    # Create a complete project structure
    prod_result = create_or_get_product(
        product_name="Full Project", vision="Complete vision"
    )
    product_id = prod_result["product_id"]

    roadmap = [
        {
            "quarter": "Q1",
            "theme_title": "Auth",
            "theme_description": "Authentication",
            "epics": [
                {
                    "epic_title": "Login",
                    "epic_summary": "Login system",
                    "features": [
                        {"title": "Email Login", "description": "Email auth"},
                        {"title": "OAuth", "description": "OAuth login"},
                    ],
                },
                {
                    "epic_title": "Registration",
                    "epic_summary": "Registration system",
                    "features": [
                        {"title": "Sign Up", "description": "User signup"},
                    ],
                },
            ],
        }
    ]
    roadmap_result = persist_roadmap(product_id, roadmap)

    # Add user stories
    for feature in roadmap_result["created"]["features"]:
        create_user_story(
            product_id=product_id,
            feature_id=feature["id"],
            title=f"Story for {feature['title']}",
            description="As a user...",
        )

    # Get details
    result = get_project_details(product_id)

    assert result["success"] is True
    assert result["product"]["name"] == "Full Project"
    assert result["structure"]["themes"] == 1
    assert result["structure"]["epics"] == 2
    assert result["structure"]["features"] == 3
    assert result["structure"]["user_stories"] == 3


def test_get_project_by_name_not_found(engine):
    """Test finding project by name when it doesn't exist."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    result = get_project_by_name("Non Existent Project")

    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_get_project_by_name_found(engine):
    """Test finding project by name successfully."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    import tools.db_tools as db_tools
    from tools.db_tools import create_or_get_product

    db_tools.engine = engine

    # Create product
    prod_result = create_or_get_product(product_name="Findable Project")
    product_id = prod_result["product_id"]

    # Find it by name
    result = get_project_by_name("Findable Project")

    assert result["success"] is True
    assert result["product_id"] == product_id
    assert result["product_name"] == "Findable Project"
