from __future__ import annotations

from typing import Optional

from sqlalchemy import delete
from sqlmodel import Session, select

from models.core import (
    SprintStory,
    Task,
    UserStory,
)
from models.db import get_engine
from models.events import StoryCompletionLog, TaskExecutionLog


class StoryRepository:
    """Repository handling database operations for story aggregates."""

    def __init__(self, session: Optional[Session] = None):
        self._session = session

    def _get_session(self) -> Session:
        return self._session if self._session else Session(get_engine())

    def delete_by_requirement(
        self,
        *,
        product_id: int,
        normalized_requirement: str,
        chunk_size: int = 500,
    ) -> int:
        """Delete stories and dependent records for one requirement."""
        session = self._get_session()
        try:
            story_ids = session.exec(
                select(UserStory.story_id).where(
                    UserStory.product_id == product_id,
                    UserStory.source_requirement == normalized_requirement,
                )
            ).all()

            deleted_count = len(story_ids)
            if story_ids:
                for i in range(0, len(story_ids), chunk_size):
                    chunk_ids = story_ids[i : i + chunk_size]

                    session.exec(
                        delete(SprintStory).where(
                            SprintStory.story_id.in_(chunk_ids)
                        )
                    )
                    session.exec(
                        delete(StoryCompletionLog).where(
                            StoryCompletionLog.story_id.in_(chunk_ids)
                        )
                    )

                    task_ids = session.exec(
                        select(Task.task_id).where(Task.story_id.in_(chunk_ids))
                    ).all()
                    if task_ids:
                        for j in range(0, len(task_ids), chunk_size):
                            task_chunk = task_ids[j : j + chunk_size]
                            session.exec(
                                delete(TaskExecutionLog).where(
                                    TaskExecutionLog.task_id.in_(task_chunk)
                                )
                            )

                    session.exec(
                        delete(Task).where(Task.story_id.in_(chunk_ids))
                    )
                    session.exec(
                        delete(UserStory).where(
                            UserStory.story_id.in_(chunk_ids)
                        )
                    )

            session.commit()
            return deleted_count
        finally:
            if not self._session:
                session.close()
