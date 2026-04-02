"""
Test suite for orchestrator decision-making tools.
Tests the query tools used by the orchestrator agent.
"""

import pytest
from sqlmodel import Session, select

from agile_sqlmodel import Product, StoryStatus, UserStory
from tools.orchestrator_tools import (
    count_projects,
    fetch_product_backlog,
    fetch_sprint_candidates,
    get_project_by_name,
    get_project_details,
    list_projects,
)


class MockToolContext:
    def __init__(self, state):
        self.state = state


def test_count_projects_empty(engine):
    """Test counting projects when database is empty."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    state = {}
    context = MockToolContext(state)
    result = count_projects({}, context)

    assert result["success"] is True
    assert result["count"] == 0
    assert "0 project" in result["message"]


def test_count_projects_with_data(engine):
    """Test counting projects when products exist."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    import tools.db_tools as db_tools
    from tools.db_tools import create_or_get_product, CreateOrGetProductInput

    db_tools.engine = engine

    # Create 3 products
    create_or_get_product(CreateOrGetProductInput(product_name="Project A", vision=None, description=None))
    create_or_get_product(CreateOrGetProductInput(product_name="Project B", vision=None, description=None))
    create_or_get_product(CreateOrGetProductInput(product_name="Project C", vision=None, description=None))

    state = {}
    context = MockToolContext(state)
    result = count_projects({}, context)

    assert result["success"] is True
    assert result["count"] == 3
    assert "3 project" in result["message"]


def test_list_projects_empty(engine):
    """Test listing projects when database is empty."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    state = {}
    context = MockToolContext(state)
    result = list_projects({}, context)

    assert result["success"] is True
    assert result["count"] == 0
    assert len(result["projects"]) == 0


def test_list_projects_with_data(engine):
    """Test listing projects with summary data."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    import tools.db_tools as db_tools
    from tools.db_tools import (
        create_or_get_product,
        create_user_story,
        persist_roadmap,
        CreateOrGetProductInput,
        CreateUserStoryInput
    )

    db_tools.engine = engine

    # Create a product with structure
    prod_result = create_or_get_product(CreateOrGetProductInput(
        product_name="Test Project", vision="Test vision", description=None
    ))
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
    create_user_story(CreateUserStoryInput(
        product_id=product_id,
        feature_id=feature_id,
        title="Login as user",
        description="As a user...",
        acceptance_criteria=None,
        story_points=None,
    ))

    # Now list projects
    state = {}
    context = MockToolContext(state)
    result = list_projects({}, context)

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
    from tools.db_tools import (
        create_or_get_product,
        create_user_story,
        persist_roadmap,
        CreateOrGetProductInput,
        CreateUserStoryInput
    )

    db_tools.engine = engine

    # Create a complete project structure
    prod_result = create_or_get_product(CreateOrGetProductInput(
        product_name="Full Project", vision="Complete vision", description=None
    ))
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
        create_user_story(CreateUserStoryInput(
            product_id=product_id,
            feature_id=feature["id"],
            title=f"Story for {feature['title']}",
            description="As a user...",
            acceptance_criteria=None,
            story_points=None,
        ))

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
    from tools.db_tools import create_or_get_product, CreateOrGetProductInput

    db_tools.engine = engine

    # Create product
    prod_result = create_or_get_product(CreateOrGetProductInput(product_name="Findable Project", vision=None, description=None))
    product_id = prod_result["product_id"]

    # Find it by name
    result = get_project_by_name("Findable Project")

    assert result["success"] is True
    assert result["product_id"] == product_id
    assert result["product_name"] == "Findable Project"


def test_fetch_sprint_candidates_only_refined_todo(session: Session) -> None:
    """Sprint candidates must include only refined, non-superseded TO_DO stories."""
    session.add(Product(product_id=21, name="Sprint Filter Project"))
    session.commit()

    refined_story = UserStory(
        product_id=21,
        title="Refined Story",
        status=StoryStatus.TO_DO,
        rank="2",
        story_points=3,
        is_refined=True,
        is_superseded=False,
        story_origin="refined",
        persona="Document Reviewer",
    )
    non_refined_story = UserStory(
        product_id=21,
        title="Backlog Seed",
        status=StoryStatus.TO_DO,
        rank="1",
        story_points=5,
        is_refined=False,
        is_superseded=False,
        story_origin="backlog_seed",
    )
    superseded_story = UserStory(
        product_id=21,
        title="Superseded Story",
        status=StoryStatus.TO_DO,
        rank="3",
        story_points=3,
        is_refined=True,
        is_superseded=True,
        story_origin="refined",
    )
    done_story = UserStory(
        product_id=21,
        title="Done Story",
        status=StoryStatus.DONE,
        rank="4",
        story_points=2,
        is_refined=True,
        is_superseded=False,
        story_origin="refined",
    )

    session.add(refined_story)
    session.add(non_refined_story)
    session.add(superseded_story)
    session.add(done_story)
    session.commit()

    result = fetch_sprint_candidates(21)

    assert result["success"] is True
    assert result["count"] == 1
    assert result["excluded_counts"] == {
        "non_refined": 1,
        "superseded": 1,
        "open_sprint": 0,
    }
    assert result["stories"][0]["story_title"] == "Refined Story"
    assert result["stories"][0]["priority"] == 2
    assert result["stories"][0]["persona"] == "Document Reviewer"


def test_fetch_product_backlog_exposes_refinement_flags(session: Session) -> None:
    """Backlog fetch should expose refinement metadata for diagnostics."""
    session.add(Product(product_id=31, name="Backlog Metadata Project"))
    session.commit()

    session.add(
        UserStory(
            product_id=31,
            title="Seed Story",
            status=StoryStatus.TO_DO,
            rank="1",
            is_refined=False,
            is_superseded=False,
            story_origin="backlog_seed",
            persona=None,
        )
    )
    session.add(
        UserStory(
            product_id=31,
            title="Refined Story",
            status=StoryStatus.TO_DO,
            rank="2",
            is_refined=True,
            is_superseded=False,
            story_origin="refined",
            persona="Data Steward",
        )
    )
    session.commit()

    result = fetch_product_backlog(31)
    assert result["success"] is True
    assert result["count"] == 2

    by_title = {story["title"]: story for story in result["stories"]}
    assert by_title["Seed Story"]["is_refined"] is False
    assert by_title["Seed Story"]["story_origin"] == "backlog_seed"
    assert by_title["Refined Story"]["is_refined"] is True
    assert by_title["Refined Story"]["story_origin"] == "refined"
