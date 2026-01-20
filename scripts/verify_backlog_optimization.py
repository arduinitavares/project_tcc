
import logging
import time
import sys
from sqlalchemy import event
from sqlmodel import Session, create_engine, SQLModel, select
from datetime import datetime, timezone

# Adjust path to import from project root
import os
sys.path.append(os.getcwd())

import agile_sqlmodel
from agile_sqlmodel import (
    Product, Theme, Epic, Feature, UserStory, StoryStatus,
    Team, Sprint, SprintStatus
)
import orchestrator_agent.agent_tools.sprint_planning.tools as tools_module
from orchestrator_agent.agent_tools.sprint_planning.tools import get_backlog_for_planning, BacklogQueryInput

# Setup logging
logging.basicConfig()
logger = logging.getLogger("sqlalchemy.engine")
logger.setLevel(logging.WARNING)

def setup_db():
    # Use in-memory DB for speed and isolation
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine

def populate_data(session, product_id):
    # Create hierarchy
    print("Creating 50 stories with unique features...")

    for i in range(50):
        theme = Theme(title=f"Theme {i}", product_id=product_id)
        session.add(theme)
        session.commit()

        epic = Epic(title=f"Epic {i}", theme_id=theme.theme_id)
        session.add(epic)
        session.commit()

        feature = Feature(title=f"Feature {i}", epic_id=epic.epic_id)
        session.add(feature)
        session.commit()

        story = UserStory(
            title=f"Story {i}",
            product_id=product_id,
            feature_id=feature.feature_id,
            status=StoryStatus.TO_DO,
            story_points=3
        )
        session.add(story)

    session.commit()

class QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        # print(f"QUERY: {statement}")

def run_benchmark():
    engine = setup_db()

    # Patch the engine in the tool module so it uses our test DB
    original_tool_engine = tools_module.engine
    tools_module.engine = engine

    try:
        with Session(engine) as session:
            product = Product(name="Benchmark Product")
            session.add(product)
            session.commit()
            session.refresh(product)
            product_id = product.product_id

            populate_data(session, product_id)

        # Setup query counter
        query_counter = QueryCounter()
        event.listen(engine, "before_cursor_execute", query_counter)

        print("\n--- Starting Benchmark ---")
        start_time = time.time()

        # Call the tool
        input_data = BacklogQueryInput(product_id=product_id)
        result = get_backlog_for_planning(input_data)

        end_time = time.time()
        duration = end_time - start_time

        print(f"\n--- Results ---")
        print(f"Total Queries: {query_counter.count}")
        print(f"Time Taken: {duration:.4f} seconds")
        print(f"Success: {result.get('success')}")
        print(f"Stories returned: {len(result.get('stories', []))}")

        if result.get("stories"):
            first_story = result["stories"][0]
            print(f"First story feature: {first_story.get('feature_title')}")
            print(f"First story theme: {first_story.get('theme_title')}")

        return query_counter.count

    finally:
        # Restore original engine
        tools_module.engine = original_tool_engine

if __name__ == "__main__":
    run_benchmark()
