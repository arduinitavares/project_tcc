"""
Pytest configuration and fixtures.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture(scope="session")
def test_db_url():
    """Return test database URL."""
    return "sqlite:///:memory:"


@pytest.fixture(scope="function")
def engine(test_db_url: str):  # pylint: disable=redefined-outer-name
    """Create a fresh in-memory database for each test."""

    # Enable foreign key support for SQLite
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Use _engine to avoid redefining the 'engine' fixture name
    _engine = create_engine(test_db_url, echo=False)

    # Import here to avoid circular imports.
    # We disable unused-import as these models are needed to populate
    # SQLModel.metadata before create_all() is called.
    from agile_sqlmodel import (  # pylint: disable=import-outside-toplevel, unused-import
        Epic,
        Feature,
        Product,
        Task,
        Team,
        TeamMember,
        Theme,
        UserStory,
    )

    # Create all tables
    SQLModel.metadata.create_all(_engine)

    yield _engine

    # Cleanup
    SQLModel.metadata.drop_all(_engine)


@pytest.fixture
def session(engine: Engine):  # pylint: disable=redefined-outer-name
    """Create a new database session for each test."""
    # Use _session to avoid redefining the 'session' fixture name
    with Session(engine) as _session:
        yield _session
