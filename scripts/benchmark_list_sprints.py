"""Script for benchmark list sprints."""

import importlib
import os
import sys
from datetime import date, timedelta
from sqlite3 import Connection
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from utils.cli_output import emit

# Add repo root to path
sys.path.append(os.getcwd())  # noqa: PTH109

from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    StoryStatus,
    UserStory,
)
from models.core import Team


def _load_legacy_sprint_query_tools() -> Any:  # noqa: ANN401
    module_name = "orchestrator_agent.agent_tools.sprint_planning.sprint_query_tools"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        msg = (
            "The list-sprints benchmark targets legacy module "
            f"{module_name!r}, which is not present in this checkout."
        )
        raise RuntimeError(msg) from exc


sprint_query_tools = _load_legacy_sprint_query_tools()


def _require_id(value: int | None, name: str) -> int:
    if value is None:
        msg = f"{name} was not generated"
        raise RuntimeError(msg)
    return value


class QueryCounter:
    """Test helper for query counter."""

    def __init__(self) -> None:
        """Initialize the test helper."""
        self.count = 0

    def __call__(  # noqa: PLR0913
        self,
        conn: object,
        cursor: object,
        statement: object,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        """Implement __call__ for the test helper."""
        del conn, cursor, statement, parameters, context, executemany
        self.count += 1


def setup_data(session: Session, product_id: int) -> None:
    # Create 5 teams
    """Return setup data."""
    teams = []
    for i in range(5):
        team = Team(name=f"Team {i}")
        session.add(team)
        teams.append(team)
    session.commit()
    for team in teams:
        session.refresh(team)
    team_ids = [
        _require_id(team.team_id, f"Team {index} ID")
        for index, team in enumerate(teams)
    ]

    # Create 20 sprints (4 per team)
    sprints = []
    base_date = date(2024, 1, 1)
    for i in range(20):
        team_id = team_ids[i % 5]
        sprint = Sprint(
            goal=f"Sprint {i}",
            start_date=base_date + timedelta(days=i * 14),
            end_date=base_date + timedelta(days=(i + 1) * 14 - 1),
            status=SprintStatus.ACTIVE,
            product_id=product_id,
            team_id=team_id,
        )
        session.add(sprint)
        sprints.append(sprint)
    session.commit()
    for sprint in sprints:
        session.refresh(sprint)
    sprint_ids = [
        _require_id(sprint.sprint_id, f"Sprint {index} ID")
        for index, sprint in enumerate(sprints)
    ]

    # Create 50 stories distributed across sprints
    for i in range(50):
        story = UserStory(
            title=f"Story {i}",
            product_id=product_id,
            status=StoryStatus.TO_DO,
            story_points=3,
        )
        session.add(story)
        session.commit()  # Get ID
        session.refresh(story)
        story_id = _require_id(story.story_id, f"Story {i} ID")

        # Assign to a sprint
        sprint_id = sprint_ids[i % 20]
        session.add(SprintStory(sprint_id=sprint_id, story_id=story_id))
    session.commit()


def run_benchmark() -> int:
    # Setup DB
    """Return run benchmark."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Enforce foreign keys
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(
        dbapi_connection: Connection, _connection_record: object
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)

    # Patch module engine
    sprint_query_tools.engine = engine

    # Setup data
    with Session(engine) as session:
        product = Product(name="Benchmark Product")
        session.add(product)
        session.commit()
        session.refresh(product)
        product_id = _require_id(product.product_id, "Product ID")

        setup_data(session, product_id)

    # Measure
    query_counter = QueryCounter()
    event.listen(engine, "before_cursor_execute", query_counter)

    emit(f"Running list_sprints for product {product_id}...")
    result = sprint_query_tools.list_sprints(product_id)

    event.remove(engine, "before_cursor_execute", query_counter)

    emit(f"Result success: {result.get('success')}")
    emit(f"Sprints found: {len(result.get('sprints', []))}")
    emit(f"Total queries executed: {query_counter.count}")

    return query_counter.count


if __name__ == "__main__":
    run_benchmark()
