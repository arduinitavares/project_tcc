"""Read-only workflow session access for agent workbench projections."""

import json
import sqlite3
from typing import Any, Protocol

from utils.runtime_config import WORKFLOW_RUNNER_IDENTITY, get_session_db_target


class _SessionRepository(Protocol):
    def get_session_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Fetch workflow session state by identity and session id."""
        ...


class ReadOnlySessionReader:
    """Read project workflow session state without creating or updating sessions."""

    def __init__(self, repository: _SessionRepository | None = None) -> None:
        """Initialize the reader with an optional session repository."""
        self._repository = (
            repository if repository is not None else _ReadOnlySessionRepository()
        )

    def get_project_state(self, project_id: int) -> dict[str, Any]:
        """Return workflow session state for a project id."""
        return self._repository.get_session_state(
            WORKFLOW_RUNNER_IDENTITY.app_name,
            WORKFLOW_RUNNER_IDENTITY.user_id,
            str(project_id),
        )


class _ReadOnlySessionRepository:
    """Read workflow session state through SQLite read-only connections."""

    def get_session_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Fetch workflow session state without creating session storage."""
        target = get_session_db_target()
        db_path = target.sqlite_path
        if db_path is None or not db_path.exists():
            return {}

        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as conn:
            if not self._has_sessions_table(conn):
                return {}
            cursor = conn.execute(
                "SELECT state FROM sessions WHERE app_name=? AND user_id=? AND id=?",
                (app_name, user_id, session_id),
            )
            row = cursor.fetchone()

        return json.loads(row[0]) if row else {}

    def _has_sessions_table(self, conn: sqlite3.Connection) -> bool:
        """Return whether the read-only connection can see the sessions table."""
        cursor = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions' LIMIT 1"
        )
        return cursor.fetchone() is not None
