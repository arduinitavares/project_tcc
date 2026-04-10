import pytest
from sqlalchemy import inspect, text
from sqlmodel import create_engine

from db.migrations import migrate_performance_indexes


def _create_min_user_stories_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE user_stories (
                    story_id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL,
                    title VARCHAR NOT NULL
                )
                """
            )
        )


def test_migrate_performance_indexes_creates_canonical_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_min_user_stories_schema(engine)

    actions = migrate_performance_indexes(engine)

    assert actions == ["created index: ix_user_stories_product_id"]
    index_names = {idx["name"] for idx in inspect(engine).get_indexes("user_stories")}
    assert "ix_user_stories_product_id" in index_names


def test_migrate_performance_indexes_is_idempotent_with_canonical_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_min_user_stories_schema(engine)
    migrate_performance_indexes(engine)

    actions = migrate_performance_indexes(engine)

    assert actions == []
    canonical_indexes = [
        idx["name"]
        for idx in inspect(engine).get_indexes("user_stories")
        if idx["name"] == "ix_user_stories_product_id"
    ]
    assert len(canonical_indexes) == 1


def test_migrate_performance_indexes_fails_on_non_canonical_equivalent_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_min_user_stories_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX legacy_user_stories_product_id ON user_stories (product_id)"
            )
        )

    with pytest.raises(RuntimeError) as exc_info:
        migrate_performance_indexes(engine)

    message = str(exc_info.value)
    assert "legacy_user_stories_product_id" in message
    assert "ix_user_stories_product_id" in message
