
import unittest
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event
from sqlalchemy.engine import Engine
from datetime import date

# Import the function to be tested
from orchestrator_agent.agent_tools.sprint_planning.sprint_query_tools import get_sprint_details, GetSprintDetailsInput

# Import db tools and models for test data setup
import tools.db_tools as db_tools
from agile_sqlmodel import (
    Product,
    Team,
    Sprint,
    UserStory,
    SprintStory,
    StoryStatus,
)

class TestSprintQueryTools(unittest.TestCase):

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
        db_tools.engine = self.engine
        # We need to do this for the module under test as well
        from orchestrator_agent.agent_tools.sprint_planning import sprint_query_tools
        sprint_query_tools.engine = self.engine


    def tearDown(self):
        """Cleanup the database after each test."""
        SQLModel.metadata.drop_all(self.engine)

    def test_get_sprint_details_n_plus_1_fix(self):
        """Test that get_sprint_details fetches stories efficiently."""
        with Session(self.engine) as session:
            # 1. Setup test data
            product = Product(name="Test Product", vision="A test product")
            session.add(product)
            session.commit()
            session.refresh(product)

            team = Team(name="Test Team")
            session.add(team)
            session.commit()
            session.refresh(team)

            sprint = Sprint(
                goal="Test Sprint",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 14),
                status="ACTIVE",
                product_id=product.product_id,
                team_id=team.team_id,
            )
            session.add(sprint)
            session.commit()
            session.refresh(sprint)

            # Create and add stories to the sprint
            story1 = UserStory(title="Story 1", product_id=product.product_id, status=StoryStatus.TO_DO, story_points=5)
            story2 = UserStory(title="Story 2", product_id=product.product_id, status=StoryStatus.IN_PROGRESS, story_points=3)
            story3 = UserStory(title="Story 3", product_id=product.product_id, status=StoryStatus.DONE, story_points=8)
            session.add_all([story1, story2, story3])
            session.commit()
            session.refresh(story1)
            session.refresh(story2)
            session.refresh(story3)

            session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story1.story_id))
            session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story2.story_id))
            session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story3.story_id))
            session.commit()

            # 2. Call the function
            result = get_sprint_details(GetSprintDetailsInput(sprint_id=sprint.sprint_id))

            # 3. Assert the results
            self.assertTrue(result["success"])
            self.assertEqual(result["sprint"]["sprint_id"], sprint.sprint_id)
            self.assertEqual(result["story_count"], 3)

            # Check stories
            story_titles = {s["title"] for s in result["stories"]}
            self.assertEqual(story_titles, {"Story 1", "Story 2", "Story 3"})

            # Check metrics
            metrics = result["metrics"]
            self.assertEqual(metrics["total_points"], 16)
            self.assertEqual(metrics["completed_points"], 8)
            self.assertAlmostEqual(metrics["completion_pct"], 50.0)

            # Check status breakdown
            status_breakdown = result["story_status_breakdown"]
            self.assertEqual(status_breakdown[StoryStatus.TO_DO.value], 1)
            self.assertEqual(status_breakdown[StoryStatus.IN_PROGRESS.value], 1)
            self.assertEqual(status_breakdown[StoryStatus.DONE.value], 1)


if __name__ == '__main__':
    unittest.main()
