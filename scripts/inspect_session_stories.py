"""Inspect and identify 'Story from session' placeholder stories."""

import sys
from pathlib import Path

from utils.cli_output import emit

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from agile_sqlmodel import UserStory, get_engine


def inspect_session_stories() -> None:
    """Find all stories with 'Story from session' or 'session state fallback' in them."""  # noqa: E501
    with Session(get_engine()) as session:
        # Find stories with the placeholder text
        all_stories = session.exec(select(UserStory)).all()

        session_stories = []
        for story in all_stories:
            if (
                "Story from session" in (story.title or "")
                or "session state fallback" in (story.story_description or "")
                or "AC from session" in (story.acceptance_criteria or "")
            ):
                session_stories.append(story)  # noqa: PERF401

        if not session_stories:
            emit("✓ No 'session' placeholder stories found")
            return

        emit(f"\n⚠️  Found {len(session_stories)} placeholder stories:\n")
        for story in session_stories:
            emit(f"Story #{story.story_id}")
            emit(f"  Title: {story.title}")
            emit(f"  Description: {story.story_description[:100]}...")
            emit(f"  Product ID: {story.product_id}")
            emit(f"  Feature ID: {story.feature_id}")
            emit(f"  Status: {story.status}")
            emit(f"  Story Points: {story.story_points}")
            emit()


if __name__ == "__main__":
    inspect_session_stories()
