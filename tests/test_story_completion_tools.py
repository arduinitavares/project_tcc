
import unittest
from datetime import datetime, timezone
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Import module to test
import orchestrator_agent.agent_tools.sprint_planning.sprint_execution_tools as sprint_tools
from agile_sqlmodel import (
    Product, UserStory, Sprint, SprintStory, StoryStatus,
    StoryResolution, StoryCompletionLog, Team
)
from orchestrator_agent.agent_tools.sprint_planning.sprint_execution_tools import (
    complete_story_with_notes,
    update_acceptance_criteria,
    create_follow_up_story,
    CompleteStoryInput,
    UpdateACInput,
    CreateFollowUpInput
)

class TestStoryCompletionTools(unittest.TestCase):

    def setUp(self):
        # Create in-memory DB
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        SQLModel.metadata.create_all(self.engine)

        # Patch engine
        sprint_tools.engine = self.engine

        # Enable FKs
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        # Seed basic data
        with Session(self.engine) as session:
            # Team
            team = Team(name="Test Team")
            session.add(team)
            session.commit()
            self.team_id = team.team_id

            # Product
            product = Product(name="Test Product")
            session.add(product)
            session.commit()
            self.product_id = product.product_id

            # Create Story
            story = UserStory(
                title="Test Story",
                acceptance_criteria="- Do the thing",
                product_id=product.product_id,
                status=StoryStatus.IN_PROGRESS
            )
            session.add(story)
            session.commit()
            self.story_id = story.story_id

            # Create Sprint
            sprint = Sprint(
                product_id=product.product_id,
                team_id=team.team_id,
                start_date=datetime.now().date(),
                end_date=datetime.now().date(),
                status="Active"
            )
            session.add(sprint)
            session.commit()
            self.sprint_id = sprint.sprint_id

            # Link story to sprint
            sprint_story = SprintStory(
                sprint_id=sprint.sprint_id,
                story_id=story.story_id,
                added_at=datetime.now(timezone.utc)
            )
            session.add(sprint_story)
            session.commit()

    def tearDown(self):
        SQLModel.metadata.drop_all(self.engine)

    def test_complete_story_with_notes_success(self):
        input_data = {
            "story_id": self.story_id,
            "sprint_id": self.sprint_id,
            "resolution": "COMPLETED",
            "delivered": "Delivered the feature successfully",
            "evidence": "http://example.com/pr/1",
            "known_gaps": "None",
        }

        result = complete_story_with_notes(input_data)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "DONE")

        with Session(self.engine) as session:
            story = session.get(UserStory, self.story_id)
            self.assertEqual(story.status, StoryStatus.DONE)
            self.assertEqual(story.resolution, StoryResolution.COMPLETED)
            self.assertEqual(story.completion_notes, "Delivered the feature successfully")
            self.assertEqual(story.evidence_links, "http://example.com/pr/1")
            self.assertIsNotNone(story.completed_at)

    def test_complete_story_creates_audit_log(self):
        input_data = {
            "story_id": self.story_id,
            "delivered": "Done",
        }
        complete_story_with_notes(input_data)

        with Session(self.engine) as session:
            logs = session.exec(select(StoryCompletionLog).where(StoryCompletionLog.story_id == self.story_id)).all()
            self.assertEqual(len(logs), 1)
            log = logs[0]
            self.assertEqual(log.old_status, StoryStatus.IN_PROGRESS)
            self.assertEqual(log.new_status, StoryStatus.DONE)
            self.assertEqual(log.resolution, StoryResolution.COMPLETED)
            self.assertEqual(log.delivered, "Done")

    def test_complete_story_with_notes_not_found(self):
        input_data = {
            "story_id": 999,
            "delivered": "Nothing"
        }
        result = complete_story_with_notes(input_data)
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_complete_story_with_notes_not_in_sprint(self):
        # Create another sprint
        with Session(self.engine) as session:
            sprint2 = Sprint(
                product_id=self.product_id,
                team_id=self.team_id,
                start_date=datetime.now().date(),
                end_date=datetime.now().date(),
                status="Planned"
            )
            session.add(sprint2)
            session.commit()
            sprint2_id = sprint2.sprint_id

        input_data = {
            "story_id": self.story_id,
            "sprint_id": sprint2_id,
            "delivered": "Done"
        }
        result = complete_story_with_notes(input_data)
        self.assertFalse(result["success"])
        self.assertIn("not in sprint", result["error"])

    def test_complete_story_with_notes_tracks_ac_changes(self):
        # First update AC via tool (or manually, but tool simulates flow)
        # Actually complete_story_with_notes handles saving original if not present

        input_data = {
            "story_id": self.story_id,
            "delivered": "Done with changes",
            "resolution": "COMPLETED_WITH_CHANGES",
            "ac_was_updated": True,
            "ac_update_reason": "Scope creep"
        }

        # Pre-condition: original_acceptance_criteria is None
        with Session(self.engine) as session:
            story = session.get(UserStory, self.story_id)
            self.assertIsNone(story.original_acceptance_criteria)
            current_ac = story.acceptance_criteria

        result = complete_story_with_notes(input_data)
        self.assertTrue(result["success"])

        with Session(self.engine) as session:
            story = session.get(UserStory, self.story_id)
            self.assertEqual(story.original_acceptance_criteria, current_ac)
            self.assertEqual(story.ac_update_reason, "Scope creep")
            self.assertEqual(story.resolution, StoryResolution.COMPLETED_WITH_CHANGES)

    def test_update_acceptance_criteria_preserves_original(self):
        new_ac = "- New Criteria"
        input_data = {
            "story_id": self.story_id,
            "new_acceptance_criteria": new_ac,
            "reason": "Clarification"
        }

        # Get original
        with Session(self.engine) as session:
            original_ac = session.get(UserStory, self.story_id).acceptance_criteria

        result = update_acceptance_criteria(input_data)
        self.assertTrue(result["success"])

        with Session(self.engine) as session:
            story = session.get(UserStory, self.story_id)
            self.assertEqual(story.acceptance_criteria, new_ac)
            self.assertEqual(story.original_acceptance_criteria, original_ac)
            self.assertEqual(story.ac_update_reason, "Clarification")
            self.assertIsNotNone(story.ac_updated_at)

    def test_update_acceptance_criteria_scope_change_suggestion(self):
        input_data = {
            "story_id": self.story_id,
            "new_acceptance_criteria": "Reduced scope",
            "reason": "Descoping",
            "is_scope_change": True
        }
        result = update_acceptance_criteria(input_data)
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["suggestion"])
        self.assertIn("follow-up", result["suggestion"])

    def test_create_follow_up_story_success(self):
        input_data = {
            "parent_story_id": self.story_id,
            "title": "Follow up story",
            "description": "Remaining work",
            "acceptance_criteria": "- Do the rest",
            "reason": "Not enough time"
        }

        result = create_follow_up_story(input_data)
        self.assertTrue(result["success"])

        new_story_id = result["new_story_id"]

        with Session(self.engine) as session:
            new_story = session.get(UserStory, new_story_id)
            self.assertEqual(new_story.title, "Follow up story")
            self.assertEqual(new_story.status, StoryStatus.TO_DO)
            self.assertEqual(new_story.product_id, self.product_id)
            self.assertIn("Follow-up from Story", new_story.story_description)
            self.assertIn(str(self.story_id), new_story.story_description)

    def test_create_follow_up_story_parent_not_found(self):
        input_data = {
            "parent_story_id": 999,
            "title": "Fail",
            "description": "Fail",
            "acceptance_criteria": "Fail",
            "reason": "Fail"
        }
        result = create_follow_up_story(input_data)
        self.assertFalse(result["success"])

if __name__ == '__main__':
    unittest.main()
