"""Tests for db migrations sprint lifecycle."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import create_engine

from db.migrations import migrate_sprint_lifecycle


def _create_min_sprints_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE sprints (
                    sprint_id INTEGER PRIMARY KEY,
                    goal TEXT,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    status VARCHAR NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    product_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL
                )
                """
            )
        )


def _create_min_sprints_schema_with_started_at(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE sprints (
                    sprint_id INTEGER PRIMARY KEY,
                    goal TEXT,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    status VARCHAR NOT NULL,
                    started_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    product_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL
                )
                """
            )
        )


def test_migrate_sprint_lifecycle_adds_lifecycle_columns() -> None:
    """Verify migrate sprint lifecycle adds lifecycle columns."""
    engine = create_engine("sqlite:///:memory:")
    _create_min_sprints_schema(engine)

    actions = migrate_sprint_lifecycle(engine)

    assert "added column: sprints.started_at" in actions
    assert "added column: sprints.completed_at" in actions
    assert "added column: sprints.close_snapshot_json" in actions
    column_names = {col["name"] for col in inspect(engine).get_columns("sprints")}
    assert "started_at" in column_names
    assert "completed_at" in column_names
    assert "close_snapshot_json" in column_names


def test_migrate_sprint_lifecycle_only_adds_missing_partial_schema_columns() -> None:
    """Verify migrate sprint lifecycle only adds missing partial schema columns."""
    engine = create_engine("sqlite:///:memory:")
    _create_min_sprints_schema_with_started_at(engine)

    actions = migrate_sprint_lifecycle(engine)

    assert actions == [
        "added column: sprints.completed_at",
        "added column: sprints.close_snapshot_json",
    ]


def test_migrate_sprint_lifecycle_is_idempotent() -> None:
    """Verify migrate sprint lifecycle is idempotent."""
    engine = create_engine("sqlite:///:memory:")
    _create_min_sprints_schema(engine)
    migrate_sprint_lifecycle(engine)

    actions = migrate_sprint_lifecycle(engine)

    assert actions == []
