"""Tests for read-only workflow session access."""

import json
import sqlite3
from pathlib import Path

import pytest

from services.agent_workbench.session_reader import ReadOnlySessionReader
from utils.runtime_config import WORKFLOW_RUNNER_IDENTITY, clear_runtime_config_cache


class _FakeSessionRepository:
    """Fake repository recording whether read access mutates state."""

    def __init__(self) -> None:
        self.updated = False

    def get_session_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, object]:
        """Return the lookup arguments in the fake session state."""
        return {
            "app_name": app_name,
            "user_id": user_id,
            "session_id": session_id,
            "fsm_state": "SPRINT_SETUP",
        }

    def update_session_state(self, *_args: object, **_kwargs: object) -> None:
        """Record a forbidden session mutation."""
        self.updated = True


def test_read_only_session_reader_fetches_state_without_update() -> None:
    """Fetch workflow state using the stable runner identity without mutation."""
    repo = _FakeSessionRepository()
    reader = ReadOnlySessionReader(repository=repo)

    state = reader.get_project_state(project_id=7)

    assert state["app_name"] == WORKFLOW_RUNNER_IDENTITY.app_name
    assert state["user_id"] == WORKFLOW_RUNNER_IDENTITY.user_id
    assert state["fsm_state"] == "SPRINT_SETUP"
    assert state["session_id"] == "7"
    assert repo.updated is False


def test_default_reader_returns_empty_for_missing_session_db_without_creating_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Avoid creating the configured session DB when it does not exist."""
    business_path = tmp_path / "business.sqlite3"
    session_path = tmp_path / "missing-sessions.sqlite3"
    monkeypatch.setenv("PROJECT_TCC_DB_URL", f"sqlite:///{business_path.as_posix()}")
    monkeypatch.setenv(
        "PROJECT_TCC_SESSION_DB_URL",
        f"sqlite:///{session_path.as_posix()}",
    )
    clear_runtime_config_cache()

    try:
        reader = ReadOnlySessionReader()

        assert reader.get_project_state(project_id=7) == {}
        assert not session_path.exists()
    finally:
        clear_runtime_config_cache()


def test_default_reader_returns_empty_when_sessions_table_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tolerate an initialized DB with no sessions table."""
    business_path = tmp_path / "business.sqlite3"
    session_path = tmp_path / "sessions.sqlite3"
    session_path.touch()
    monkeypatch.setenv("PROJECT_TCC_DB_URL", f"sqlite:///{business_path.as_posix()}")
    monkeypatch.setenv(
        "PROJECT_TCC_SESSION_DB_URL",
        f"sqlite:///{session_path.as_posix()}",
    )
    clear_runtime_config_cache()

    try:
        reader = ReadOnlySessionReader()

        assert reader.get_project_state(project_id=7) == {}
    finally:
        clear_runtime_config_cache()


def test_default_reader_fetches_existing_session_with_read_only_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fetch an existing session row through the default read-only repository."""
    business_path = tmp_path / "business.sqlite3"
    session_path = tmp_path / "sessions.sqlite3"
    with sqlite3.connect(session_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                app_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                id TEXT NOT NULL,
                state TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (app_name, user_id, id, state)
            VALUES (?, ?, ?, ?)
            """,
            (
                WORKFLOW_RUNNER_IDENTITY.app_name,
                WORKFLOW_RUNNER_IDENTITY.user_id,
                "7",
                json.dumps({"fsm_state": "SPRINT_SETUP"}),
            ),
        )
    monkeypatch.setenv("PROJECT_TCC_DB_URL", f"sqlite:///{business_path.as_posix()}")
    monkeypatch.setenv(
        "PROJECT_TCC_SESSION_DB_URL",
        f"sqlite:///{session_path.as_posix()}",
    )
    clear_runtime_config_cache()

    try:
        reader = ReadOnlySessionReader()

        assert reader.get_project_state(project_id=7) == {
            "fsm_state": "SPRINT_SETUP"
        }
    finally:
        clear_runtime_config_cache()
