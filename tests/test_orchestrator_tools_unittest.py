"""Tests for orchestrator tools unittest."""

import unittest
from sqlite3 import Connection

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, create_engine

# Import the modules to be tested
import tools.orchestrator_tools as orch_tools
from tests.typing_helpers import make_tool_context
from tools import db_tools
from tools.db_tools import (
    CreateOrGetProductInput,
    CreateUserStoryInput,
    create_or_get_product,
    create_user_story,
    persist_roadmap,
)


class TestOrchestratorTools(unittest.TestCase):
    """Test helper for test orchestrator tools."""

    def setUp(self) -> None:
        """Create a fresh in-memory database for each test."""

        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: Connection, _connection_record: object
        ) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.engine = create_engine("sqlite:///:memory:", echo=False)

        SQLModel.metadata.create_all(self.engine)

        self._previous_orchestrator_get_engine = orch_tools.get_engine
        self._previous_db_get_engine = db_tools.get_engine
        orch_tools.__dict__["get_engine"] = lambda: self.engine
        db_tools.__dict__["get_engine"] = lambda: self.engine

    def tearDown(self) -> None:
        """Cleanup the database after each test."""
        orch_tools.__dict__["get_engine"] = self._previous_orchestrator_get_engine
        db_tools.__dict__["get_engine"] = self._previous_db_get_engine
        SQLModel.metadata.drop_all(self.engine)

    def test_count_projects_empty(self) -> None:
        """Test counting projects when database is empty."""
        state = {}
        context = make_tool_context(state)
        result = orch_tools.count_projects({}, context)
        assert result["success"]
        assert result["count"] == 0
        assert "0 project" in result["message"]

    def test_count_projects_with_data(self) -> None:
        """Test counting projects when products exist."""
        create_or_get_product(
            CreateOrGetProductInput(
                product_name="Project A", vision=None, description=None
            )
        )
        create_or_get_product(
            CreateOrGetProductInput(
                product_name="Project B", vision=None, description=None
            )
        )
        create_or_get_product(
            CreateOrGetProductInput(
                product_name="Project C", vision=None, description=None
            )
        )
        state = {}
        context = make_tool_context(state)
        result = orch_tools.count_projects({}, context)
        assert result["success"]
        assert result["count"] == 3  # noqa: PLR2004

    def test_get_story_details_tool(self) -> None:
        """Test fetching story details via db_tools."""
        product_result = create_or_get_product(
            CreateOrGetProductInput(
                product_name="Story Details Integration",
                vision="Integration test vision",
                description=None,
            )
        )
        product_id = product_result["product_id"]

        roadmap = [
            {
                "theme_title": "Integration Theme",
                "theme_description": "Theme for integration test",
                "epics": [
                    {
                        "epic_title": "Integration Epic",
                        "epic_summary": "Epic for integration test",
                        "features": [
                            {
                                "title": "Integration Feature",
                                "description": "Feature for integration test",
                            },
                        ],
                    }
                ],
            }
        ]

        roadmap_result = persist_roadmap(product_id, roadmap)
        feature_id = roadmap_result["created"]["features"][0]["id"]

        story_result = create_user_story(
            CreateUserStoryInput(
                product_id=product_id,
                feature_id=feature_id,
                title="Integration Story",
                description="As a user, I want to fetch story details so that I can inspect them.",  # noqa: E501
                story_points=2,
                acceptance_criteria="- Details can be retrieved",
            )
        )
        story_id = story_result["story_id"]

        result = db_tools.get_story_details(story_id)

        assert result["success"]
        assert result["story_id"] == story_id
        assert result["title"] == "Integration Story"
        assert result["feature_id"] == feature_id
        assert result["product_id"] == product_id

    def test_list_projects_empty(self) -> None:
        """Test listing projects when database is empty."""
        state = {}
        context = make_tool_context(state)
        result = orch_tools.list_projects({}, context)
        assert result["success"]
        assert result["count"] == 0
        assert len(result["projects"]) == 0

    def test_list_projects_with_wrapped_params_string(self) -> None:
        """Test listing projects when params are wrapped as a JSON string."""
        state = {}
        context = make_tool_context(state)
        result = orch_tools.list_projects({"params": "{}"}, context)
        assert result["success"]
        assert result["count"] == 0
        assert len(result["projects"]) == 0

    def test_list_projects_with_data(self) -> None:
        """Test listing projects with summary data."""
        prod_result = create_or_get_product(
            CreateOrGetProductInput(
                product_name="Test Project", vision="Test vision", description=None
            )
        )
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
        create_user_story(
            CreateUserStoryInput(
                product_id=product_id,
                feature_id=feature_id,
                title="Login as user",
                description="As a user...",
                acceptance_criteria=None,
                story_points=None,
            )
        )
        state = {}
        context = make_tool_context(state)
        result = orch_tools.list_projects({}, context)
        assert result["success"]
        assert result["count"] == 1
        assert len(result["projects"]) == 1
        project = result["projects"][0]
        assert project["product_id"] == product_id
        assert project["name"] == "Test Project"
        assert project["vision"] == "Test vision"
        assert project["user_stories_count"] == 1

    def test_count_projects_with_wrapped_params_string(self) -> None:
        """Test counting projects when params are wrapped as a JSON string."""
        state = {}
        context = make_tool_context(state)
        result = orch_tools.count_projects({"params": "{}"}, context)
        assert result["success"]
        assert result["count"] == 0

    def test_get_project_details_not_found(self) -> None:
        """Test getting details for non-existent project."""
        result = orch_tools.get_project_details(999)
        assert not result["success"]
        assert "not found" in result["error"].lower()

    def test_get_project_details_with_structure(self) -> None:
        """Test getting detailed structure of a project."""
        prod_result = create_or_get_product(
            CreateOrGetProductInput(
                product_name="Full Project", vision="Complete vision", description=None
            )
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
        for feature in roadmap_result["created"]["features"]:
            create_user_story(
                CreateUserStoryInput(
                    product_id=product_id,
                    feature_id=feature["id"],
                    title=f"Story for {feature['title']}",
                    description="As a user...",
                    acceptance_criteria=None,
                    story_points=None,
                )
            )
        result = orch_tools.get_project_details(product_id)
        assert result["success"]
        assert result["product"]["name"] == "Full Project"
        assert result["structure"]["themes"] == 1
        assert result["structure"]["epics"] == 2  # noqa: PLR2004
        assert result["structure"]["features"] == 3  # noqa: PLR2004
        assert result["structure"]["user_stories"] == 3  # noqa: PLR2004

    def test_get_project_by_name_not_found(self) -> None:
        """Test finding project by name when it doesn't exist."""
        result = orch_tools.get_project_by_name("Non Existent Project")
        assert not result["success"]
        assert "not found" in result["error"].lower()

    def test_get_project_by_name_found(self) -> None:
        """Test finding project by name successfully."""
        prod_result = create_or_get_product(
            CreateOrGetProductInput(
                product_name="Findable Project", vision=None, description=None
            )
        )
        product_id = prod_result["product_id"]
        result = orch_tools.get_project_by_name("Findable Project")
        assert result["success"]
        assert result["product_id"] == product_id
        assert result["product_name"] == "Findable Project"


if __name__ == "__main__":
    unittest.main()
