"""Script for verify backlog optimization."""

import logging

# Adjust path to import from project root
import os
import sys
import time

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from utils.cli_output import emit

sys.path.append(os.getcwd())  # noqa: PTH109

from agile_sqlmodel import Product, StoryStatus, UserStory
from models.core import Epic, Feature, Team, Theme
from services import orchestrator_query_service
from tools.orchestrator_tools import fetch_sprint_candidates

_MODEL_IMPORT_BOUNDARY = (Team,)

# Setup logging
logging.basicConfig()
logger = logging.getLogger("sqlalchemy.engine")
logger.setLevel(logging.WARNING)


def setup_db() -> Engine:
    # Use in-memory DB for speed and isolation
    """Return setup db."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def _require_id(value: int | None, name: str) -> int:
    if value is None:
        msg = f"{name} was not generated"
        raise RuntimeError(msg)
    return value


def populate_data(session: Session, product_id: int) -> None:
    # Create hierarchy
    """Return populate data."""
    emit("Creating 50 stories with unique features...")

    for i in range(50):
        theme = Theme(title=f"Theme {i}", product_id=product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)
        theme_id = _require_id(theme.theme_id, "Theme ID")

        epic = Epic(title=f"Epic {i}", theme_id=theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)
        epic_id = _require_id(epic.epic_id, "Epic ID")

        feature = Feature(title=f"Feature {i}", epic_id=epic_id)
        session.add(feature)
        session.commit()
        session.refresh(feature)
        feature_id = _require_id(feature.feature_id, "Feature ID")

        story = UserStory(
            title=f"Story {i}",
            product_id=product_id,
            feature_id=feature_id,
            status=StoryStatus.TO_DO,
            story_points=3,
            story_description=f"As an operator, I want story {i}.",
            acceptance_criteria="- Given a benchmark story\n- Then it is queryable",
            source_requirement=f"feature-{i}",
            refinement_slot=1,
            story_origin="refined",
            is_refined=True,
        )
        session.add(story)

    session.commit()


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
        # print(f"QUERY: {statement}")  # noqa: ERA001


def run_benchmark() -> int:
    """Return run benchmark."""
    engine = setup_db()

    # Patch the engine in the tool module so it uses our test DB
    original_get_engine = orchestrator_query_service.get_engine

    def benchmark_engine() -> Engine:
        return engine

    orchestrator_query_service.__dict__["get_engine"] = benchmark_engine

    try:
        with Session(engine) as session:
            product = Product(name="Benchmark Product")
            session.add(product)
            session.commit()
            session.refresh(product)
            product_id = _require_id(product.product_id, "Product ID")

            populate_data(session, product_id)

        # Setup query counter
        query_counter = QueryCounter()
        event.listen(engine, "before_cursor_execute", query_counter)

        emit("\n--- Starting Benchmark ---")
        start_time = time.time()

        # Call the tool
        result = fetch_sprint_candidates(product_id)

        end_time = time.time()
        duration = end_time - start_time

        emit("\n--- Results ---")
        emit(f"Total Queries: {query_counter.count}")
        emit(f"Time Taken: {duration:.4f} seconds")
        emit(f"Success: {result.get('success')}")
        emit(f"Stories returned: {len(result.get('stories', []))}")

        if result.get("stories"):
            first_story = result["stories"][0]
            emit(f"First story title: {first_story.get('story_title')}")
            emit(f"First story requirement: {first_story.get('source_requirement')}")

        return query_counter.count

    finally:
        # Restore original engine
        orchestrator_query_service.__dict__["get_engine"] = original_get_engine


if __name__ == "__main__":
    run_benchmark()
