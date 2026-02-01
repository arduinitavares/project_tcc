"""Inspect and identify 'Story from session' placeholder stories."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select
from agile_sqlmodel import engine, UserStory

def inspect_session_stories():
    """Find all stories with 'Story from session' or 'session state fallback' in them."""
    with Session(engine) as session:
        # Find stories with the placeholder text
        all_stories = session.exec(select(UserStory)).all()
        
        session_stories = []
        for story in all_stories:
            if (
                "Story from session" in (story.title or "")
                or "session state fallback" in (story.story_description or "")
                or "AC from session" in (story.acceptance_criteria or "")
            ):
                session_stories.append(story)
        
        if not session_stories:
            print("✓ No 'session' placeholder stories found")
            return
        
        print(f"\n⚠️  Found {len(session_stories)} placeholder stories:\n")
        for story in session_stories:
            print(f"Story #{story.story_id}")
            print(f"  Title: {story.title}")
            print(f"  Description: {story.story_description[:100]}...")
            print(f"  Product ID: {story.product_id}")
            print(f"  Feature ID: {story.feature_id}")
            print(f"  Status: {story.status}")
            print(f"  Story Points: {story.story_points}")
            print()

if __name__ == "__main__":
    inspect_session_stories()
