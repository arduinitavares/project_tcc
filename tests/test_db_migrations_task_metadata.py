from sqlalchemy import inspect, text
from sqlmodel import create_engine

from db.migrations import migrate_task_metadata
from utils.task_metadata import canonical_task_metadata_json


def _create_min_tasks_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE tasks (
                    task_id INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    status VARCHAR,
                    created_at DATETIME,
                    updated_at DATETIME,
                    story_id INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO tasks (task_id, description, status, created_at, updated_at, story_id)
                VALUES
                    (1, 'Legacy task A', 'To Do', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 101),
                    (2, 'Legacy task B', 'To Do', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 101)
                """
            )
        )


def test_migrate_task_metadata_adds_column_and_backfills_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_min_tasks_schema(engine)

    actions = migrate_task_metadata(engine)

    assert "added column: tasks.metadata_json" in actions
    assert any(
        action.startswith("backfilled tasks.metadata_json rows:") for action in actions
    )
    column_names = {col["name"] for col in inspect(engine).get_columns("tasks")}
    assert "metadata_json" in column_names

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT metadata_json FROM tasks ORDER BY task_id")
        ).all()
    assert rows == [
        (canonical_task_metadata_json(),),
        (canonical_task_metadata_json(),),
    ]


def test_migrate_task_metadata_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_min_tasks_schema(engine)
    migrate_task_metadata(engine)

    actions = migrate_task_metadata(engine)

    assert actions == []
