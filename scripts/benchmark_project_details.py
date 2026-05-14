"""Script for benchmark project details."""

import sys
import time
from pathlib import Path

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

from utils.cli_output import emit

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agile_sqlmodel import Product, StoryStatus, UserStory
from models.core import Epic, Feature, Theme
from tools.orchestrator_tools import get_project_details

# Setup in-memory DB for benchmarking
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)

# Patch the engine in orchestrator_tools
import tools.orchestrator_tools  # noqa: E402


def _benchmark_engine() -> Engine:
    return engine


tools.orchestrator_tools.__dict__["get_engine"] = _benchmark_engine


def _require_id(value: int | None, name: str) -> int:
    if value is None:
        msg = f"{name} was not generated"
        raise RuntimeError(msg)
    return value


def seed_database(
    product_count: int = 1,
    themes_per_product: int = 10,
    epics_per_theme: int = 10,
    features_per_epic: int = 10,
    stories_per_feature: int = 5,
) -> None:
    """Return seed database."""
    del stories_per_feature
    with Session(engine) as session:
        for p in range(product_count):
            product = Product(
                name=f"Product {p}", vision="Vision", description="Description"
            )
            session.add(product)
            session.commit()
            session.refresh(product)

            product_id = _require_id(product.product_id, "Product ID")

            for t in range(themes_per_product):
                theme = Theme(
                    title=f"Theme {t}", description="Desc", product_id=product_id
                )
                session.add(theme)
                session.flush()  # Flush to get IDs
                theme_id = _require_id(theme.theme_id, "Theme ID")

                for e in range(epics_per_theme):
                    epic = Epic(title=f"Epic {e}", summary="Sum", theme_id=theme_id)
                    session.add(epic)
                    session.flush()
                    epic_id = _require_id(epic.epic_id, "Epic ID")

                    for f in range(features_per_epic):
                        feature = Feature(
                            title=f"Feature {f}",
                            description="Desc",
                            epic_id=epic_id,
                        )
                        session.add(feature)
                        session.flush()
                        feature_id = _require_id(feature.feature_id, "Feature ID")

                        # Add some stories directly to product (backlog)
                        # And maybe some connected to feature (not strictly needed for this N+1 check on themes/epics/features structure)  # noqa: E501
                        # but get_project_details counts all stories for product.

                        # Just add one story per feature to verify story counting too if needed,  # noqa: E501
                        # though get_project_details queries stories by product_id directly so it is not the main N+1 source usually.  # noqa: E501
                        story = UserStory(
                            title=f"Story {f}",
                            story_description="Desc",
                            status=StoryStatus.TO_DO,
                            product_id=product_id,
                            feature_id=feature_id,
                        )
                        session.add(story)

        session.commit()
    emit(
        f"Seeded DB with {product_count} products, {themes_per_product} themes/prod, {epics_per_theme} epics/theme, {features_per_epic} features/epic."  # noqa: E501
    )


def benchmark() -> None:
    # Reset query count
    """Return benchmark."""
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

    # Measure
    start_time = time.time()
    # Assuming product_id 1 is the one created
    result = get_project_details(1)
    end_time = time.time()

    duration = end_time - start_time

    emit(f"Execution Time: {duration:.4f} seconds")
    emit(f"Query Count: {query_count}")

    if not result["success"]:
        emit("Error in get_project_details")
        sys.exit(1)

    emit(f"Structure returned: {result['structure']}")


if __name__ == "__main__":
    emit("Seeding database...")
    seed_database()
    emit("Running benchmark...")
    benchmark()
