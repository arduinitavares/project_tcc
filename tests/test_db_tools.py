# tests/test_db_tools.py
"""
Test suite for db_tools module using TDD approach.
Run with: pytest tests/test_db_tools.py -v
"""

# Monkey-patch the engine for tests
import sys
from pathlib import Path

import pytest
from sqlmodel import Session, select

import tools.db_tools as db_tools
from agile_sqlmodel import Epic, Feature, Product, Task, Theme, UserStory
from tools.db_tools import (
    create_or_get_product,
    create_task,
    create_user_story,
    persist_roadmap,
)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_create_product_new(engine):
    """Test creating a new product."""
    # Patch db_tools to use test engine
    import tools.db_tools as db_tools

    db_tools.engine = engine

    from tools.db_tools import create_or_get_product

    result = create_or_get_product(
        product_name="Test Project",
        vision="To revolutionize testing",
    )

    assert result["success"] is True
    assert result["action"] == "created"
    assert result["product_id"] == 1
    assert "Test Project" in result["message"]


def test_create_product_existing(engine):
    """Test getting an existing product without duplication."""

    db_tools.engine = engine

    # Create first product
    result1 = create_or_get_product(product_name="Existing Project")
    assert result1["action"] == "created"

    # Get same product again
    result2 = create_or_get_product(product_name="Existing Project")
    assert result2["action"] == "updated"
    assert result2["product_id"] == result1["product_id"]

    # Verify only one product exists
    with Session(engine) as session:
        products = session.exec(select(Product)).all()
        assert len(products) == 1


def test_persist_roadmap(engine):
    """Test persisting a roadmap hierarchy."""

    db_tools.engine = engine

    # Create product first
    prod_result = create_or_get_product(product_name="Roadmap Project")
    product_id = prod_result["product_id"]

    # Define roadmap
    roadmap = [
        {
            "quarter": "Q1",
            "theme_title": "Authentication",
            "theme_description": "User identity and access",
            "epics": [
                {
                    "epic_title": "Login System",
                    "epic_summary": "Email and OAuth login",
                    "features": [
                        {"title": "Email Login", "description": "Basic email/password"},
                        {"title": "OAuth 2.0", "description": "Third-party login"},
                    ],
                }
            ],
        }
    ]

    # Persist roadmap
    result = persist_roadmap(product_id, roadmap)

    assert result["success"] is True
    assert result["created"]["themes"][0]["id"] == 1
    assert len(result["created"]["epics"]) == 1
    assert len(result["created"]["features"]) == 2

    # Verify hierarchy in database
    with Session(engine) as session:
        themes = session.exec(select(Theme)).all()
        assert len(themes) == 1
        assert themes[0].product_id == product_id

        epics = session.exec(select(Epic)).all()
        assert len(epics) == 1
        assert epics[0].theme_id == themes[0].theme_id

        features = session.exec(select(Feature)).all()
        assert len(features) == 2


def test_create_user_story(engine):
    """Test creating a user story under a feature."""

    db_tools.engine = engine

    # Setup hierarchy
    prod_result = create_or_get_product(product_name="Story Project")
    product_id = prod_result["product_id"]

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

    # Create user story
    story_result = create_user_story(
        product_id=product_id,
        feature_id=feature_id,
        title="Login with email",
        description="As a user, I want to log in with email and password.",
        acceptance_criteria="User can enter email/password and be authenticated.",
        story_points=5,
    )

    assert story_result["success"] is True
    assert story_result["story_id"] == 1
    assert story_result["feature_id"] == feature_id

    # Verify in database
    with Session(engine) as session:
        stories = session.exec(select(UserStory)).all()
        assert len(stories) == 1
        assert stories[0].story_points == 5


def test_create_task(engine):
    """Test creating a task under a story."""

    db_tools.engine = engine

    # Setup full hierarchy
    prod_result = create_or_get_product(product_name="Task Project")
    product_id = prod_result["product_id"]

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

    story_result = create_user_story(
        product_id=product_id,
        feature_id=feature_id,
        title="Login with email",
        description="As a user, I want to log in.",
    )
    story_id = story_result["story_id"]

    # Create task
    task_result = create_task(
        story_id=story_id,
        title="Set up email validation",
        description="Implement email regex validation",
    )

    assert task_result["success"] is True
    assert task_result["task_id"] == 1

    # Verify in database
    with Session(engine) as session:
        tasks = session.exec(select(Task)).all()
        assert len(tasks) == 1


def test_query_product_structure(engine):
    """Test querying full product structure."""
    import tools.db_tools as db_tools

    db_tools.engine = engine

    from tools.db_tools import (
        create_or_get_product,
        create_user_story,
        persist_roadmap,
        query_product_structure,
    )

    # Setup hierarchy
    prod_result = create_or_get_product(
        product_name="Query Project", vision="Test vision statement"
    )
    product_id = prod_result["product_id"]

    roadmap = [
        {
            "quarter": "Q1",
            "theme_title": "Auth",
            "theme_description": "Authentication features",
            "epics": [
                {
                    "epic_title": "Login",
                    "epic_summary": "Login implementation",
                    "features": [
                        {"title": "Email Login", "description": "Email auth"},
                    ],
                }
            ],
        }
    ]

    roadmap_result = persist_roadmap(product_id, roadmap)
    feature_id = roadmap_result["created"]["features"][0]["id"]

    create_user_story(
        product_id=product_id,
        feature_id=feature_id,
        title="User can login",
        description="As a user...",
        story_points=5,
    )

    # Query structure
    result = query_product_structure(product_id)

    assert result["success"] is True
    assert result["structure"]["product"]["name"] == "Query Project"
    assert result["structure"]["product"]["vision"] == "Test vision statement"
    assert len(result["structure"]["themes"]) == 1
    assert len(result["structure"]["themes"][0]["epics"]) == 1
    assert len(result["structure"]["themes"][0]["epics"][0]["features"]) == 1
    assert (
        len(result["structure"]["themes"][0]["epics"][0]["features"][0]["stories"]) == 1
    )
