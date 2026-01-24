
import time
import sys
from pathlib import Path
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy import Engine, event

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.orchestrator_tools import get_project_details
from agile_sqlmodel import Product, Theme, Epic, Feature, UserStory, StoryStatus

# Setup in-memory DB for benchmarking
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)

# Patch the engine in orchestrator_tools
import tools.orchestrator_tools
tools.orchestrator_tools.engine = engine

def seed_database(product_count=1, themes_per_product=10, epics_per_theme=10, features_per_epic=10, stories_per_feature=5):
    with Session(engine) as session:
        for p in range(product_count):
            product = Product(name=f"Product {p}", vision="Vision", description="Description")
            session.add(product)
            session.commit()
            session.refresh(product)

            product_id = product.product_id

            for t in range(themes_per_product):
                theme = Theme(title=f"Theme {t}", description="Desc", product_id=product_id)
                session.add(theme)
                session.flush() # Flush to get IDs

                for e in range(epics_per_theme):
                    epic = Epic(title=f"Epic {e}", summary="Sum", theme_id=theme.theme_id)
                    session.add(epic)
                    session.flush()

                    for f in range(features_per_epic):
                        feature = Feature(title=f"Feature {f}", description="Desc", epic_id=epic.epic_id)
                        session.add(feature)
                        session.flush()

                        # Add some stories directly to product (backlog)
                        # And maybe some connected to feature (not strictly needed for this N+1 check on themes/epics/features structure)
                        # but get_project_details counts all stories for product.

                        # Just add one story per feature to verify story counting too if needed,
                        # though get_project_details queries stories by product_id directly so it is not the main N+1 source usually.
                        story = UserStory(
                                title=f"Story {f}",
                                story_description="Desc",
                                status=StoryStatus.TO_DO,
                                product_id=product_id,
                                feature_id=feature.feature_id
                        )
                        session.add(story)

        session.commit()
    print(f"Seeded DB with {product_count} products, {themes_per_product} themes/prod, {epics_per_theme} epics/theme, {features_per_epic} features/epic.")

def benchmark():
    # Reset query count
    query_count = 0

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    # Measure
    start_time = time.time()
    # Assuming product_id 1 is the one created
    result = get_project_details(1)
    end_time = time.time()

    duration = end_time - start_time

    print(f"Execution Time: {duration:.4f} seconds")
    print(f"Query Count: {query_count}")

    if not result["success"]:
        print("Error in get_project_details")
        sys.exit(1)

    print(f"Structure returned: {result['structure']}")

if __name__ == "__main__":
    print("Seeding database...")
    seed_database()
    print("Running benchmark...")
    benchmark()
