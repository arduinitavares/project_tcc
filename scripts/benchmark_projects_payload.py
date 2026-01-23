
import time
import sys
import random
from pathlib import Path
from typing import Dict, Any
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy import Engine, event

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.orchestrator_tools import _refresh_projects_cache
from agile_sqlmodel import Product, UserStory, StoryStatus

# Setup in-memory DB for benchmarking
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)

# Patch the engine in orchestrator_tools
import tools.orchestrator_tools
tools.orchestrator_tools.engine = engine

def seed_database(product_count=50, min_stories=10, max_stories=20):
    print(f"Seeding database with {product_count} products...")
    with Session(engine) as session:
        for p in range(product_count):
            product = Product(name=f"Product {p}", vision="Vision", description="Description")
            session.add(product)
            session.flush() # flush to get ID

            num_stories = random.randint(min_stories, max_stories)
            for s in range(num_stories):
                story = UserStory(
                    title=f"Story {s} for Product {p}",
                    story_description="Desc",
                    status=StoryStatus.TO_DO,
                    product_id=product.product_id
                )
                session.add(story)
        session.commit()

    # Verify count
    with Session(engine) as session:
        p_count = len(session.exec(select(Product)).all())
        s_count = len(session.exec(select(UserStory)).all())
        print(f"Seeded: {p_count} products, {s_count} total stories.")

from sqlmodel import select

def benchmark():
    # Mock state
    state: Dict[str, Any] = {}

    # Reset query count
    query_count = 0

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    print("Running _refresh_projects_cache...")

    # Measure
    start_time = time.time()
    count, projects = _refresh_projects_cache(state)
    end_time = time.time()

    duration = end_time - start_time

    print("-" * 30)
    print(f"Execution Time: {duration:.4f} seconds")
    print(f"Query Count:    {query_count}")
    print(f"Projects Found: {count}")
    print("-" * 30)

    if count == 0:
        print("Error: No projects returned!")
        sys.exit(1)

if __name__ == "__main__":
    seed_database()
    benchmark()
