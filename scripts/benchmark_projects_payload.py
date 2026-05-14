"""Script for benchmark projects payload."""

import secrets
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine, select

from utils.cli_output import emit

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agile_sqlmodel import Product, StoryStatus, UserStory
from services import orchestrator_query_service
from tools.orchestrator_tools import _refresh_projects_cache

# Setup in-memory DB for benchmarking
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)


def _benchmark_engine() -> Engine:
    return engine


orchestrator_query_service.__dict__["get_engine"] = _benchmark_engine


def _random_story_count(min_stories: int, max_stories: int) -> int:
    return min_stories + secrets.randbelow(max_stories - min_stories + 1)


def _require_id(value: int | None, name: str) -> int:
    if value is None:
        msg = f"{name} was not generated"
        raise RuntimeError(msg)
    return value


def seed_database(
    product_count: int = 50, min_stories: int = 10, max_stories: int = 20
) -> None:
    """Return seed database."""
    emit(f"Seeding database with {product_count} products...")
    with Session(engine) as session:
        for p in range(product_count):
            product = Product(
                name=f"Product {p}", vision="Vision", description="Description"
            )
            session.add(product)
            session.flush()  # flush to get ID
            product_id = _require_id(product.product_id, "Product ID")

            num_stories = _random_story_count(min_stories, max_stories)
            for s in range(num_stories):
                story = UserStory(
                    title=f"Story {s} for Product {p}",
                    story_description="Desc",
                    status=StoryStatus.TO_DO,
                    product_id=product_id,
                )
                session.add(story)
        session.commit()

    # Verify count
    with Session(engine) as session:
        p_count = len(session.exec(select(Product)).all())
        s_count = len(session.exec(select(UserStory)).all())
        emit(f"Seeded: {p_count} products, {s_count} total stories.")


def benchmark() -> None:
    # Mock state
    """Return benchmark."""
    state: dict[str, Any] = {}

    # Reset query count
    query_count = 0

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(  # noqa: PLR0913
        conn: object,
        cursor: object,
        statement: object,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        del conn, cursor, statement, parameters, context, executemany
        nonlocal query_count
        query_count += 1

    emit("Running _refresh_projects_cache...")

    # Measure
    start_time = time.time()
    count, _projects = _refresh_projects_cache(state)
    end_time = time.time()

    duration = end_time - start_time

    emit("-" * 30)
    emit(f"Execution Time: {duration:.4f} seconds")
    emit(f"Query Count:    {query_count}")
    emit(f"Projects Found: {count}")
    emit("-" * 30)

    if count == 0:
        emit("Error: No projects returned!")
        sys.exit(1)


if __name__ == "__main__":
    seed_database()
    benchmark()
