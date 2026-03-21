import pytest
import sqlite3
import tempfile
import json
import os
from repositories.session import WorkflowSessionRepository


class TempDBTarget:
    def __init__(self, path):
        self.sqlite_connect_target = path
        self.sqlite_url = f"sqlite:///{path}"


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


def test_get_session_states_batch(temp_db):
    target = TempDBTarget(temp_db)
    repo = WorkflowSessionRepository(db_target=target)

    # 1. No table yet
    assert repo.get_session_states_batch("app1", "user1", ["1", "2"]) == {}

    # 2. Empty list
    assert repo.get_session_states_batch("app1", "user1", []) == {}

    # 3. Create table and insert rows
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE sessions (id TEXT, app_name TEXT, user_id TEXT, state TEXT)"
        )
        cursor.execute(
            "INSERT INTO sessions VALUES ('sid1', 'app1', 'user1', '{\"fsm_state\":\"A\"}')"
        )
        cursor.execute(
            "INSERT INTO sessions VALUES ('sid2', 'app1', 'user1', '{\"fsm_state\":\"B\"}')"
        )
        cursor.execute(
            "INSERT INTO sessions VALUES ('sid_wrong_app', 'app2', 'user1', '{\"fsm_state\":\"C\"}')"
        )
        cursor.execute(
            "INSERT INTO sessions VALUES ('sid_wrong_user', 'app1', 'user2', '{\"fsm_state\":\"D\"}')"
        )
        cursor.execute(
            "INSERT INTO sessions VALUES ('sid_empty_state', 'app1', 'user1', '')"
        )
        conn.commit()

    # Test batch fetch
    results = repo.get_session_states_batch(
        "app1",
        "user1",
        ["sid1", "sid2", "sid3", "sid_wrong_app", "sid_wrong_user", "sid_empty_state"],
    )

    assert len(results) == 3
    assert results["sid1"] == {"fsm_state": "A"}
    assert results["sid2"] == {"fsm_state": "B"}
    assert "sid3" not in results  # unknown id
    assert "sid_wrong_app" not in results  # wrong app
    assert "sid_wrong_user" not in results  # wrong user
    assert (
        results["sid_empty_state"] == {}
    )  # Empty state handles empty string gracefully


def test_get_session_states_batch_chunking(temp_db):
    target = TempDBTarget(temp_db)
    repo = WorkflowSessionRepository(db_target=target)

    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE sessions (id TEXT, app_name TEXT, user_id TEXT, state TEXT)"
        )
        for i in range(1001):
            cursor.execute(
                "INSERT INTO sessions VALUES (?, 'app1', 'user1', ?)",
                (f"sid_{i}", json.dumps({"idx": i})),
            )
        conn.commit()

    ids = [f"sid_{i}" for i in range(1001)]
    results = repo.get_session_states_batch("app1", "user1", ids)

    assert len(results) == 1001
    assert results["sid_0"]["idx"] == 0
    assert results["sid_1000"]["idx"] == 1000


def _create_sessions_table(conn):
    conn.execute(
        "CREATE TABLE sessions (id TEXT, app_name TEXT, user_id TEXT, state TEXT)"
    )


def test_get_session_state_malformed_json(temp_db):
    target = TempDBTarget(temp_db)
    repo = WorkflowSessionRepository(db_target=target)

    with sqlite3.connect(temp_db) as conn:
        _create_sessions_table(conn)
        conn.execute(
            "INSERT INTO sessions VALUES ('sid_bad', 'app1', 'user1', 'not-valid-json')"
        )
        conn.commit()

    result = repo.get_session_state("app1", "user1", "sid_bad")
    assert result == {}


def test_get_session_states_batch_malformed_json(temp_db):
    target = TempDBTarget(temp_db)
    repo = WorkflowSessionRepository(db_target=target)

    with sqlite3.connect(temp_db) as conn:
        _create_sessions_table(conn)
        conn.execute(
            "INSERT INTO sessions VALUES ('sid_ok', 'app1', 'user1', '{\"k\": 1}')"
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('sid_bad', 'app1', 'user1', 'not-valid-json')"
        )
        conn.commit()

    results = repo.get_session_states_batch("app1", "user1", ["sid_ok", "sid_bad"])
    assert results["sid_ok"] == {"k": 1}
    assert results["sid_bad"] == {}
