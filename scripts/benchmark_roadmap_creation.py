"""Script for benchmark roadmap creation."""

import importlib
import os
import sys
import time
from typing import Any

from utils.cli_output import emit

# Add the current directory to sys.path to make sure we can import modules
sys.path.append(os.getcwd())  # noqa: PTH109

from sqlalchemy import create_engine, event
from sqlmodel import Session, SQLModel

from agile_sqlmodel import Product

# Setup in-memory DB
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)

# Query counter
query_count = 0


def _load_legacy_roadmap_tools() -> Any:  # noqa: ANN401
    module_name = "orchestrator_agent.agent_tools.product_roadmap_agent.tools"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        msg = (
            "The roadmap creation benchmark targets legacy module "
            f"{module_name!r}, which is not present in this checkout."
        )
        raise RuntimeError(msg) from exc


_legacy_roadmap_tools = _load_legacy_roadmap_tools()
RoadmapThemeInput = _legacy_roadmap_tools.RoadmapThemeInput
_create_structure_from_themes = _legacy_roadmap_tools._create_structure_from_themes


@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(  # noqa: PLR0913
    conn: object,
    cursor: object,
    statement: object,
    parameters: object,
    context: object,
    executemany: object,
) -> None:
    """Return before cursor execute."""
    del conn, cursor, statement, parameters, context, executemany
    global query_count  # noqa: PLW0603
    query_count += 1


def _require_id(value: int | None, name: str) -> int:
    if value is None:
        msg = f"{name} was not generated"
        raise RuntimeError(msg)
    return value


def setup_data(session: Session) -> int:
    """Return setup data."""
    product = Product(name="Benchmark Product")
    session.add(product)
    session.commit()
    session.refresh(product)
    return _require_id(product.product_id, "Product ID")


def generate_themes(count: int = 20, features_per_theme: int = 10) -> list[Any]:
    """Return generate themes."""
    themes = []
    for i in range(count):
        themes.append(  # noqa: PERF401
            RoadmapThemeInput(
                theme_name=f"Theme {i}",
                key_features=[f"Feature {j}" for j in range(features_per_theme)],
                justification="Benchmark",
                time_frame="Now",
            )
        )
    return themes


def run_benchmark() -> None:
    """Return run benchmark."""
    global query_count  # noqa: PLW0603

    with Session(engine) as session:
        product_id = setup_data(session)
        themes = generate_themes(count=20, features_per_theme=10)
        # 20 themes, 20 epics, 200 features.
        # Expected commits in unoptimized: 20 + 20 + 200 = 240 commits?
        # Plus select queries if any (refresh involves select)

        emit(
            f"Starting benchmark with {len(themes)} themes and {len(themes) * 10} features..."  # noqa: E501
        )
        query_count = 0
        start_time = time.time()

        _create_structure_from_themes(session, product_id, themes)

        end_time = time.time()
        emit(f"Result: {end_time - start_time:.4f} seconds, {query_count} queries")


if __name__ == "__main__":
    run_benchmark()
