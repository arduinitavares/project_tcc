
import time
import sys
from pathlib import Path
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy import Engine, event

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.db_tools import query_product_structure
from agile_sqlmodel import Product, Theme, Epic, Feature, UserStory, StoryStatus

# Setup in-memory DB for benchmarking
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)

# Patch the engine in db_tools
import tools.db_tools
tools.db_tools.engine = engine

def seed_database(product_count=1, themes_per_product=5, epics_per_theme=5, features_per_epic=5, stories_per_feature=5):
    with Session(engine) as session:
        for p in range(product_count):
            product = Product(name=f"Product {p}", vision="Vision", description="Description")
            session.add(product)
            session.commit()
            session.refresh(product)

            for t in range(themes_per_product):
                theme = Theme(title=f"Theme {t}", description="Desc", product_id=product.product_id)
                session.add(theme)
                session.commit()
                session.refresh(theme)

                for e in range(epics_per_theme):
                    epic = Epic(title=f"Epic {e}", summary="Sum", theme_id=theme.theme_id)
                    session.add(epic)
                    session.commit()
                    session.refresh(epic)

                    for f in range(features_per_epic):
                        feature = Feature(title=f"Feature {f}", description="Desc", epic_id=epic.epic_id)
                        session.add(feature)
                        session.commit()
                        session.refresh(feature)

                        for s in range(stories_per_feature):
                            story = UserStory(
                                title=f"Story {s}",
                                story_description="Desc",
                                status=StoryStatus.TO_DO,
                                product_id=product.product_id,
                                feature_id=feature.feature_id
                            )
                            session.add(story)
        session.commit()
    print(f"Seeded DB with {product_count} products, {themes_per_product} themes/prod, {epics_per_theme} epics/theme, {features_per_epic} features/epic, {stories_per_feature} stories/feature.")

def benchmark():
    # Reset query count
    query_count = 0

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    # Measure
    start_time = time.time()
    result = query_product_structure(1)
    end_time = time.time()

    duration = end_time - start_time

    print(f"Execution Time: {duration:.4f} seconds")
    print(f"Query Count: {query_count}")

    if not result["success"]:
        print("Error in query_product_structure")
        sys.exit(1)

if __name__ == "__main__":
    print("Seeding database...")
    seed_database()
    print("Running benchmark...")
    benchmark()
