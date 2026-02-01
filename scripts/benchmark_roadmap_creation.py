import time
import sys
import os
# Add the current directory to sys.path to make sure we can import modules
sys.path.append(os.getcwd())

from sqlalchemy import event, create_engine
from sqlmodel import Session, SQLModel
# Import the function to test
from orchestrator_agent.agent_tools.product_roadmap_agent.tools import _create_structure_from_themes, RoadmapThemeInput
from agile_sqlmodel import Product

# Setup in-memory DB
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)

# Query counter
query_count = 0

@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    global query_count
    query_count += 1

def setup_data(session):
    product = Product(name="Benchmark Product")
    session.add(product)
    session.commit()
    session.refresh(product)
    return product.product_id

def generate_themes(count=20, features_per_theme=10):
    themes = []
    for i in range(count):
        themes.append(RoadmapThemeInput(
            theme_name=f"Theme {i}",
            key_features=[f"Feature {j}" for j in range(features_per_theme)],
            justification="Benchmark",
            time_frame="Now"
        ))
    return themes

def run_benchmark():
    global query_count

    with Session(engine) as session:
        product_id = setup_data(session)
        themes = generate_themes(count=20, features_per_theme=10)
        # 20 themes, 20 epics, 200 features.
        # Expected commits in unoptimized: 20 + 20 + 200 = 240 commits?
        # Plus select queries if any (refresh involves select)

        print(f"Starting benchmark with {len(themes)} themes and {len(themes)*10} features...")
        query_count = 0
        start_time = time.time()

        _create_structure_from_themes(session, product_id, themes)

        end_time = time.time()
        print(f"Result: {end_time - start_time:.4f} seconds, {query_count} queries")

if __name__ == "__main__":
    run_benchmark()
