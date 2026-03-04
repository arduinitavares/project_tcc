import sqlite3
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class WorkflowSessionRepository:
    """Repository handling volatile session state using sqlite3."""
    
    def __init__(self, db_path: str = "agile_sqlmodel.db"):
        self.db_path = db_path

    def get_session_state(self, app_name: str, user_id: str, session_id: str) -> Dict[str, Any]:
        """Fetch raw state dict from SQLite (Acts as Volatile RAM)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state FROM sessions WHERE app_name=? AND user_id=? AND id=?",
                (app_name, user_id, session_id),
            )
            row = cursor.fetchone()
            conn.close()
            state: Dict[str, Any] = json.loads(row[0]) if row else {}
            logger.debug("Retrieved session state (redacted).")
            return state
        except (sqlite3.Error, json.JSONDecodeError) as e:
            logger.error("Error fetching state from DB: %s", e)
            return {}

    def update_session_state(self, app_name: str, user_id: str, session_id: str, partial_update: Dict[str, Any]) -> None:
        """Updates the Volatile State with a partial update dict."""
        current_state = self.get_session_state(app_name, user_id, session_id)
        current_state.update(partial_update)

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET state=? WHERE app_name=? AND user_id=? AND id=?",
                (json.dumps(current_state), app_name, user_id, session_id),
            )
            conn.commit()
            conn.close()
            logger.info("Session state updated successfully in DB")
        except sqlite3.Error as e:
            logger.error("DB WRITE ERROR: %s", e)
            raise RuntimeError(f"Database write error updating session: {e}")
