"""Tests for delete_project script."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Epic,
    Feature,
    Product,
    ProductTeam,
    SpecRegistry,
    Sprint,
    SprintStory,
    StoryCompletionLog,
    StoryStatus,
    Task,
    Team,
    Theme,
    UserStory,
)
from scripts.delete_project import delete_project


def _create_sqlite_engine(db_path: Path) -> Engine:
    """Create a SQLite engine with foreign keys enabled."""

    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return engine


def test_delete_project_removes_sprints_and_story_logs(tmp_path: Path) -> None:
    """Ensure delete_project clears sprints and story completion logs."""

    db_path = tmp_path / "delete_project_test.db"
    engine = _create_sqlite_engine(db_path)

    with Session(engine) as session:
        product = Product(name="Test Product")
        team = Team(name="Test Team")
        session.add(product)
        session.add(team)
        session.flush()
        product_id = product.product_id

        session.add(ProductTeam(product_id=product.product_id, team_id=team.team_id))

        theme = Theme(title="Theme", product_id=product.product_id)
        session.add(theme)
        session.flush()

        epic = Epic(title="Epic", theme_id=theme.theme_id)
        session.add(epic)
        session.flush()

        feature = Feature(title="Feature", epic_id=epic.epic_id)
        session.add(feature)
        session.flush()

        story = UserStory(
            title="Story",
            product_id=product.product_id,
            feature_id=feature.feature_id,
        )
        session.add(story)
        session.flush()

        session.add(Task(description="Task", story_id=story.story_id))

        sprint = Sprint(
            goal="Goal",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=7),
            product_id=product.product_id,
            team_id=team.team_id,
        )
        session.add(sprint)
        session.flush()

        session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story.story_id))
        session.add(
            StoryCompletionLog(
                story_id=story.story_id,
                old_status=StoryStatus.TO_DO,
                new_status=StoryStatus.DONE,
            )
        )
        session.commit()

    delete_project(product_id, str(db_path))

    with Session(engine) as session:
        product_exists = session.exec(
            select(Product).where(Product.product_id == product_id)
        ).first()
        assert product_exists is None
        sprint_exists = session.exec(
            select(Sprint).where(Sprint.product_id == product_id)
        ).first()
        assert sprint_exists is None
        assert session.exec(select(UserStory)).first() is None
        assert session.exec(select(StoryCompletionLog)).first() is None
        assert session.exec(select(Task)).first() is None
        assert session.exec(select(Feature)).first() is None
        assert session.exec(select(Epic)).first() is None
        assert session.exec(select(Theme)).first() is None


def test_delete_project_removes_compiled_spec_authority(tmp_path: Path) -> None:
    """Ensure delete_project clears compiled spec authority records."""

    db_path = tmp_path / "delete_project_spec.db"
    engine = _create_sqlite_engine(db_path)

    with Session(engine) as session:
        product = Product(name="Spec Product")
        session.add(product)
        session.flush()
        product_id = product.product_id

        spec = SpecRegistry(
            product_id=product_id,
            spec_hash="spec-hash",
            content="# Spec",
            status="approved",
        )
        session.add(spec)
        session.flush()

        session.add(
            CompiledSpecAuthority(
                spec_version_id=spec.spec_version_id,
                compiler_version="1.0.0",
                prompt_hash="prompt-hash",
                scope_themes="[]",
                invariants="[]",
                eligible_feature_ids="[]",
            )
        )
        session.commit()

    delete_project(product_id, str(db_path))

    with Session(engine) as session:
        assert session.exec(select(CompiledSpecAuthority)).first() is None
        assert session.exec(select(SpecRegistry)).first() is None
