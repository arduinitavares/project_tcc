
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, date
from sqlmodel import Session, SQLModel, create_engine, select
import os

from agile_sqlmodel import Product, Team, Sprint, UserStory, SprintStory, StoryStatus
from orchestrator_agent.agent_tools.sprint_planning import sprint_execution_tools

# Setup test database
TEST_DB = "edge_cases.db"
DB_URL = f"sqlite:///{TEST_DB}"

class TestSprintModification(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(DB_URL)
        # Patch the engine in the tool module
        sprint_execution_tools.engine = cls.engine

    def setUp(self):
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        # Create base data
        self.product = Product(name="Test Product")
        self.team = Team(name="Test Team")
        self.session.add(self.product)
        self.session.add(self.team)
        self.session.commit()

        self.sprint1 = Sprint(
            product_id=self.product.product_id,
            team_id=self.team.team_id,
            start_date=date.today(),
            end_date=date.today(),
            status="ACTIVE"
        )
        self.sprint2 = Sprint(
            product_id=self.product.product_id,
            team_id=self.team.team_id,
            start_date=date.today(),
            end_date=date.today(),
            status="ACTIVE"
        )
        self.session.add(self.sprint1)
        self.session.add(self.sprint2)
        self.session.commit()

        # Create stories
        self.stories = []
        for i in range(10):
            story = UserStory(title=f"Story {i}", product_id=self.product.product_id, status=StoryStatus.TO_DO, story_points=1)
            self.session.add(story)
            self.stories.append(story)
        self.session.commit()
        self.story_ids = [s.story_id for s in self.stories]

    def tearDown(self):
        self.session.close()
        SQLModel.metadata.drop_all(self.engine)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_duplicate_add_ids(self):
        # Adding same story multiple times in list
        story_id = self.story_ids[0]
        result = sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "add_story_ids": [story_id, story_id, story_id]
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["add_count"], 1)
        # Check it's only added once in DB
        links = self.session.exec(select(SprintStory).where(SprintStory.sprint_id == self.sprint1.sprint_id)).all()
        self.assertEqual(len(links), 1)

    def test_already_in_sprint(self):
        story_id = self.story_ids[0]
        # Add once
        sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "add_story_ids": [story_id]
        })

        # Try add again
        result = sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "add_story_ids": [story_id]
        })

        self.assertTrue(result["success"]) # Method succeeds overall, but reports individual errors
        self.assertEqual(result["add_count"], 0)
        self.assertEqual(len(result["add_errors"]), 1)
        self.assertIn("Already in sprint", result["add_errors"][0]["error"])

    def test_in_other_active_sprint(self):
        story_id = self.story_ids[0]
        # Add to Sprint 2
        sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint2.sprint_id,
            "add_story_ids": [story_id]
        })

        # Try add to Sprint 1
        result = sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "add_story_ids": [story_id]
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["add_count"], 0)
        self.assertEqual(len(result["add_errors"]), 1)
        self.assertIn(f"Already in sprint {self.sprint2.sprint_id}", result["add_errors"][0]["error"])

    def test_remove_story(self):
        story_id = self.story_ids[0]
        # Add first
        sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "add_story_ids": [story_id]
        })

        # Verify status IN_PROGRESS
        story = self.session.get(UserStory, story_id)
        self.session.refresh(story)
        self.assertEqual(story.status, StoryStatus.IN_PROGRESS)

        # Remove
        result = sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "remove_story_ids": [story_id]
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["remove_count"], 1)

        # Verify status reverted to TO_DO
        self.session.refresh(story)
        self.assertEqual(story.status, StoryStatus.TO_DO)

        # Verify link gone
        link = self.session.exec(select(SprintStory).where(SprintStory.story_id == story_id)).first()
        self.assertIsNone(link)

    def test_remove_done_story(self):
        story_id = self.story_ids[0]
        # Add first
        sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "add_story_ids": [story_id]
        })

        # Mark as DONE
        story = self.session.get(UserStory, story_id)
        story.status = StoryStatus.DONE
        self.session.add(story)
        self.session.commit()

        # Try remove
        result = sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "remove_story_ids": [story_id]
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["remove_count"], 0)
        self.assertIn("Cannot remove completed story", result["remove_errors"][0]["error"])

    def test_non_existent_story(self):
        result = sprint_execution_tools.modify_sprint_stories({
            "sprint_id": self.sprint1.sprint_id,
            "add_story_ids": [99999]
        })
        self.assertEqual(len(result["add_errors"]), 1)
        self.assertIn("Story not found", result["add_errors"][0]["error"])

if __name__ == "__main__":
    unittest.main()
