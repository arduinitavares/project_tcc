
import unittest
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Import the functions to be tested
from tools.orchestrator_tools import (
    count_projects,
    get_project_by_name,
    get_project_details,
    list_projects,
)
import tools.orchestrator_tools as orch_tools
import tools.db_tools as db_tools
from tools.db_tools import create_or_get_product, create_user_story, persist_roadmap
from agile_sqlmodel import (
    Epic,
    Feature,
    Product,
    Task,
    Team,
    TeamMember,
    Theme,
    UserStory,
)

class TestOrchestratorTools(unittest.TestCase):

    def setUp(self):
        """Create a fresh in-memory database for each test."""

        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.engine = create_engine("sqlite:///:memory:", echo=False)

        SQLModel.metadata.create_all(self.engine)

        # Inject the test engine into the modules
        orch_tools.engine = self.engine
        db_tools.engine = self.engine

    def tearDown(self):
        """Cleanup the database after each test."""
        SQLModel.metadata.drop_all(self.engine)

    def test_count_projects_empty(self):
        """Test counting projects when database is empty."""
        result = count_projects()
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertIn("0 project", result["message"])

    def test_count_projects_with_data(self):
        """Test counting projects when products exist."""
        create_or_get_product(product_name="Project A")
        create_or_get_product(product_name="Project B")
        create_or_get_product(product_name="Project C")
        result = count_projects()
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 3)
        self.assertIn("3 project", result["message"])

    def test_list_projects_empty(self):
        """Test listing projects when database is empty."""
        result = list_projects()
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(len(result["projects"]), 0)

    def test_list_projects_with_data(self):
        """Test listing projects with summary data."""
        prod_result = create_or_get_product(
            product_name="Test Project", vision="Test vision"
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
            product_id=product_id,
            feature_id=feature_id,
            title="Login as user",
            description="As a user...",
        )
        result = list_projects()
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["projects"]), 1)
        project = result["projects"][0]
        self.assertEqual(project["product_id"], product_id)
        self.assertEqual(project["name"], "Test Project")
        self.assertEqual(project["vision"], "Test vision")
        self.assertEqual(project["user_stories_count"], 1)

    def test_get_project_details_not_found(self):
        """Test getting details for non-existent project."""
        result = get_project_details(999)
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"].lower())

    def test_get_project_details_with_structure(self):
        """Test getting detailed structure of a project."""
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
        for feature in roadmap_result["created"]["features"]:
            create_user_story(
                product_id=product_id,
                feature_id=feature["id"],
                title=f"Story for {feature['title']}",
                description="As a user...",
            )
        result = get_project_details(product_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["product"]["name"], "Full Project")
        self.assertEqual(result["structure"]["themes"], 1)
        self.assertEqual(result["structure"]["epics"], 2)
        self.assertEqual(result["structure"]["features"], 3)
        self.assertEqual(result["structure"]["user_stories"], 3)

    def test_get_project_by_name_not_found(self):
        """Test finding project by name when it doesn't exist."""
        result = get_project_by_name("Non Existent Project")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"].lower())

    def test_get_project_by_name_found(self):
        """Test finding project by name successfully."""
        prod_result = create_or_get_product(product_name="Findable Project")
        product_id = prod_result["product_id"]
        result = get_project_by_name("Findable Project")
        self.assertTrue(result["success"])
        self.assertEqual(result["product_id"], product_id)
        self.assertEqual(result["product_name"], "Findable Project")

if __name__ == '__main__':
    unittest.main()
