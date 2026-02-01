import unittest
from datetime import date

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Import db tools and models for test data setup
import tools.db_tools as db_tools
from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    StoryStatus,
    Task,
    TaskStatus,
    Team,
    UserStory,
)

# Import the function to be tested
from orchestrator_agent.agent_tools.sprint_planning.sprint_query_tools import (
    GetSprintDetailsInput,
    get_sprint_details,
    list_sprints,
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
                status=SprintStatus.ACTIVE,
                product_id=product.product_id,
                team_id=team.team_id,
            )
            session.add(sprint)
            session.commit()
            session.refresh(sprint)

            # Create and add stories to the sprint
            story1 = UserStory(
                title="Story 1",
                product_id=product.product_id,
                status=StoryStatus.TO_DO,
                story_points=5,
            )
            story2 = UserStory(
                title="Story 2",
                product_id=product.product_id,
                status=StoryStatus.IN_PROGRESS,
                story_points=3,
            )
            story3 = UserStory(
                title="Story 3",
                product_id=product.product_id,
                status=StoryStatus.DONE,
                story_points=8,
            )
            session.add_all([story1, story2, story3])
            session.commit()
            session.refresh(story1)
            session.refresh(story2)
            session.refresh(story3)

            session.add(
                SprintStory(sprint_id=sprint.sprint_id, story_id=story1.story_id)
            )
            session.add(
                SprintStory(sprint_id=sprint.sprint_id, story_id=story2.story_id)
            )
            session.add(
                SprintStory(sprint_id=sprint.sprint_id, story_id=story3.story_id)
            )
            session.commit()

            # Create tasks for the stories
            task1 = Task(
                description="Task 1 for Story 1",
                status=TaskStatus.TO_DO,
                story_id=story1.story_id,
            )
            task2 = Task(
                description="Task 2 for Story 1",
                status=TaskStatus.IN_PROGRESS,
                story_id=story1.story_id,
            )
            task3 = Task(
                description="Task 1 for Story 2",
                status=TaskStatus.DONE,
                story_id=story2.story_id,
            )
            task4 = Task(
                description="Task 2 for Story 2",
                status=TaskStatus.DONE,
                story_id=story2.story_id,
            )
            session.add_all([task1, task2, task3, task4])
            session.commit()

            # 2. Call the function
            result = get_sprint_details(
                GetSprintDetailsInput(sprint_id=sprint.sprint_id)
            )

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
            self.assertEqual(status_breakdown[StoryStatus.ACCEPTED.value], 0)

            # Verify all enum status values are present in the breakdown
            for status in StoryStatus:
                self.assertIn(
                    status.value,
                    status_breakdown,
                    f"Status {status.value} should be present in breakdown",
                )

            # Check task count
            self.assertEqual(result["task_count"], 4)

            # Check tasks list structure
            self.assertIn("tasks", result)
            self.assertEqual(len(result["tasks"]), 4)

            # Verify task data structure
            task_descriptions = {t["description"] for t in result["tasks"]}
            self.assertEqual(
                task_descriptions,
                {
                    "Task 1 for Story 1",
                    "Task 2 for Story 1",
                    "Task 1 for Story 2",
                    "Task 2 for Story 2",
                },
            )

            # Check task status breakdown
            task_status_breakdown = result["task_status_breakdown"]
            self.assertEqual(task_status_breakdown[TaskStatus.TO_DO.value], 1)
            self.assertEqual(task_status_breakdown[TaskStatus.IN_PROGRESS.value], 1)
            self.assertEqual(task_status_breakdown[TaskStatus.DONE.value], 2)

    def test_list_sprints(self):
        """Test list_sprints returns correct data with optimization."""
        with Session(self.engine) as session:
            # 1. Setup test data
            product = Product(name="Test Product 2", vision="A test product")
            session.add(product)
            session.commit()
            session.refresh(product)

            team = Team(name="Test Team 2")
            session.add(team)
            session.commit()
            session.refresh(team)

            # Create 2 sprints
            sprint1 = Sprint(
                goal="Sprint 1",
                start_date=date(2024, 2, 1),
                end_date=date(2024, 2, 14),
                status=SprintStatus.COMPLETED,
                product_id=product.product_id,
                team_id=team.team_id,
            )
            sprint2 = Sprint(
                goal="Sprint 2",
                start_date=date(2024, 2, 15),
                end_date=date(2024, 2, 28),
                status=SprintStatus.ACTIVE,
                product_id=product.product_id,
                team_id=team.team_id,
            )
            session.add(sprint1)
            session.add(sprint2)
            session.commit()
            session.refresh(sprint1)
            session.refresh(sprint2)

            # Add stories to sprint 1
            story1 = UserStory(title="S1 Story 1", product_id=product.product_id)
            story2 = UserStory(title="S1 Story 2", product_id=product.product_id)
            session.add(story1)
            session.add(story2)
            session.commit()

            session.add(
                SprintStory(sprint_id=sprint1.sprint_id, story_id=story1.story_id)
            )
            session.add(
                SprintStory(sprint_id=sprint1.sprint_id, story_id=story2.story_id)
            )

            # Add stories to sprint 2
            story3 = UserStory(title="S2 Story 1", product_id=product.product_id)
            session.add(story3)
            session.commit()

            session.add(
                SprintStory(sprint_id=sprint2.sprint_id, story_id=story3.story_id)
            )
            session.commit()

            # 2. Call list_sprints
            result = list_sprints(product.product_id)

            # 3. Assertions
            self.assertTrue(result["success"])
            self.assertEqual(result["sprint_count"], 2)
            sprints = result["sprints"]
            self.assertEqual(len(sprints), 2)

            # Sort by start date desc (expected default)
            s1_result = next(s for s in sprints if s["sprint_id"] == sprint1.sprint_id)
            s2_result = next(s for s in sprints if s["sprint_id"] == sprint2.sprint_id)

            self.assertEqual(s1_result["story_count"], 2)
            self.assertEqual(s1_result["team_name"], "Test Team 2")
            self.assertEqual(s2_result["story_count"], 1)
            self.assertEqual(s2_result["team_name"], "Test Team 2")


if __name__ == "__main__":
    unittest.main()
