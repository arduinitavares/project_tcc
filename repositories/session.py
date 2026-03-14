import sqlite3
import json
import logging
from typing import Dict, Any, Optional

from utils.runtime_config import DatabaseTarget, get_session_db_target

logger = logging.getLogger(__name__)


class WorkflowSessionRepository:
    """Repository handling volatile session state using sqlite3."""

    def __init__(self, db_target: Optional[DatabaseTarget] = None):
        self.db_target = db_target or get_session_db_target()
        self.db_path = self.db_target.sqlite_connect_target
        self.db_url = self.db_target.sqlite_url

    def has_sessions_table(self) -> bool:
        """Return whether the ADK session schema has been initialized."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions' LIMIT 1"
            )
            return cursor.fetchone() is not None

    def get_session_state(self, app_name: str, user_id: str, session_id: str) -> Dict[str, Any]:
        """Fetch raw state dict from SQLite (Acts as Volatile RAM)."""
        if not self.has_sessions_table():
            logger.debug("Session store is not initialized yet; returning empty state.")
            return {}

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state FROM sessions WHERE app_name=? AND user_id=? AND id=?",
                (app_name, user_id, session_id),
            )
            row = cursor.fetchone()

        state: Dict[str, Any] = json.loads(row[0]) if row else {}
        logger.debug("Retrieved session state (redacted).")
        return state

    def update_session_state(self, app_name: str, user_id: str, session_id: str, partial_update: Dict[str, Any]) -> None:
        """Updates the Volatile State with a partial update dict."""
        if not self.has_sessions_table():
            raise RuntimeError(
                "Session store is not initialized: sessions table is missing."
            )

        current_state = self.get_session_state(app_name, user_id, session_id)
        current_state.update(partial_update)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET state=? WHERE app_name=? AND user_id=? AND id=?",
                (json.dumps(current_state), app_name, user_id, session_id),
            )
            conn.commit()
        logger.info("Session state updated successfully in DB")
