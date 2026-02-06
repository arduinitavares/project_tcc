"""
Pytest configuration and fixtures.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


_TEST_MODEL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "models.test.yaml"
os.environ.setdefault("MODEL_CONFIG_PATH", str(_TEST_MODEL_CONFIG_PATH))
os.environ.setdefault("RELAX_ZDR_FOR_TESTS", "true")

from utils import model_config  # pylint: disable=wrong-import-position

model_config.clear_config_cache()


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
    # Use StaticPool to ensure in-memory DB persists across connections in the same test
    _engine = create_engine(
        test_db_url,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    # Import here to avoid circular imports.
    # We disable unused-import as these models are needed to populate
    # SQLModel.metadata before create_all() is called.
    from agile_sqlmodel import (  # pylint: disable=import-outside-toplevel, unused-import
        CompiledSpecAuthority,
        Epic,
        Feature,
        Product,
        Sprint,
        SprintStory,
        SpecRegistry,
        Task,
        Team,
        TeamMember,
        Theme,
        UserStory,
        WorkflowEvent,
    )

    # Create all tables
    SQLModel.metadata.create_all(_engine)

    yield _engine

    # Cleanup
    SQLModel.metadata.drop_all(_engine)


@pytest.fixture(autouse=True)
def patch_get_engine_globally(engine, monkeypatch):
    """
    Automatically patch get_engine() in all modules to return the test engine.
    
    This ensures tests never accidentally hit the production database.
    The autouse=True means this runs for every test automatically.
    """
    # Patch the agile_sqlmodel module's get_engine function
    import agile_sqlmodel
    monkeypatch.setattr(agile_sqlmodel, "get_engine", lambda: engine)
    
    # Also patch in all modules that import get_engine
    # These need explicit patching because they import at module load time
    modules_to_patch = [
        "orchestrator_agent.agent_tools.story_pipeline.save",
        "orchestrator_agent.agent_tools.story_pipeline.batch",
        "orchestrator_agent.agent_tools.story_pipeline.single_story",
        "orchestrator_agent.agent_tools.story_pipeline.steps.setup",
        "orchestrator_agent.agent_tools.product_vision_tool.tools",
        "orchestrator_agent.agent_tools.product_roadmap_agent.tools",
        "orchestrator_agent.agent_tools.sprint_planner_tool.tools",
        "tools.story_query_tools",
        "tools.orchestrator_tools",
        "tools.db_tools",
        "tools.spec_tools",
    ]
    
    for module_path in modules_to_patch:
        try:
            import importlib
            module = importlib.import_module(module_path)
            if hasattr(module, "get_engine"):
                monkeypatch.setattr(module, "get_engine", lambda: engine)
        except ImportError:
            pass  # Module not imported in this test, skip


@pytest.fixture
def session(engine: Engine):  # pylint: disable=redefined-outer-name
    """Create a new database session for each test."""
    # Use _session to avoid redefining the 'session' fixture name
    with Session(engine) as _session:
        yield _session
