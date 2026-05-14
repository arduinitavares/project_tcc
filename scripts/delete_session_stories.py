"""Delete the 'Story from session' placeholder stories."""

import sys
from pathlib import Path

from utils.cli_output import emit

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session

from agile_sqlmodel import UserStory, engine


def delete_session_placeholder_stories() -> None:
    """Delete all stories with 'Story from session' placeholder text."""
    story_ids_to_delete = [1, 2, 4, 5, 6, 7, 12]

    with Session(engine) as session:
        deleted_count = 0
        for story_id in story_ids_to_delete:
            story = session.get(UserStory, story_id)
            if story:
                emit(f"Deleting Story #{story_id}: {story.title}")
                session.delete(story)
                deleted_count += 1
            else:
                emit(f"⚠️  Story #{story_id} not found (may have been already deleted)")

        session.commit()
        emit(f"\n✓ Deleted {deleted_count} placeholder stories")


if __name__ == "__main__":
    response = input(
        "This will DELETE stories #1, #2, #4, #5, #6, #7, #12. Continue? (yes/no): "
    )
    if response.lower() == "yes":
        delete_session_placeholder_stories()
    else:
        emit("Aborted.")
