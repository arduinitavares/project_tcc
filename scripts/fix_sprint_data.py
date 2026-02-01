"""Fix corrupted sprint data for product 2."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agile_sqlmodel import engine, UserStory, Sprint, SprintStory, StoryStatus, Task, WorkflowEvent
from sqlmodel import Session, select, text

def main():
    with Session(engine) as s:
        # List all tables
        print("=== DATABASE TABLES ===")
        result = s.exec(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [r[0] for r in result.all()]
        print(f"Tables: {tables}")
        
        # Check workflow events referencing sprint 1
        print("\n=== WORKFLOW EVENTS REFERENCING SPRINT 1 ===")
        events = s.exec(select(WorkflowEvent).where(WorkflowEvent.sprint_id == 1)).all()
        print(f"Events: {len(events)}")
        for e in events:
            print(f"  Event {e.event_id}: {e.event_type}")
        
        # Delete workflow events first
        print("\n=== DELETING WORKFLOW EVENTS ===")
        for e in events:
            s.delete(e)
            print(f"  Deleted event {e.event_id}")
        
        # Check tasks linked to stories in sprint 1
        print("\n=== TASKS LINKED TO STORIES ===")
        story_ids = [8, 9, 10, 11, 14]
        for sid in story_ids:
            tasks = s.exec(select(Task).where(Task.story_id == sid)).all()
            if tasks:
                print(f"  Story {sid} has {len(tasks)} tasks")
                for t in tasks:
                    s.delete(t)
                    print(f"    Deleted task {t.task_id}")
        
        # Delete SprintStory links
        print("\n=== DELETING SPRINT-STORY LINKS ===")
        sprint_stories = s.exec(select(SprintStory).where(SprintStory.sprint_id == 1)).all()
        for ss in sprint_stories:
            s.delete(ss)
            print(f"  Deleted link: sprint_id={ss.sprint_id}, story_id={ss.story_id}")
        
        # Reset stories to TO_DO
        print("\n=== RESETTING STORIES TO TO_DO ===")
        story_ids = [8, 9, 10, 11, 14]
        for sid in story_ids:
            story = s.get(UserStory, sid)
            if story:
                story.status = StoryStatus.TO_DO
                s.add(story)
                print(f"  Story {sid}: reset to TO_DO")
        
        # Delete Sprint 1
        print("\n=== DELETING SPRINT 1 ===")
        sprint = s.get(Sprint, 1)
        if sprint:
            s.delete(sprint)
            print("  Sprint 1 deleted")
        
        # Commit all changes
        s.commit()
        print("\n=== COMMITTED SUCCESSFULLY ===")
        
        # Verify
        print("\n=== VERIFICATION ===")
        stories = s.exec(select(UserStory).where(UserStory.product_id == 2)).all()
        for st in stories:
            print(f"Story {st.story_id}: status={st.status.value}")
        
        sprints = s.exec(select(Sprint).where(Sprint.product_id == 2)).all()
        print(f"Sprints for product 2: {len(sprints)}")

if __name__ == "__main__":
    main()
