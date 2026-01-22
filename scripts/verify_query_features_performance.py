
import time
import sys
import os
from sqlmodel import Session, SQLModel, create_engine, select
from typing import Dict, Any

# Ensure we can import from root
sys.path.append(os.getcwd())

from agile_sqlmodel import Product, Theme, Epic, Feature, UserStory, engine
from orchestrator_agent.agent_tools.product_user_story_tool.tools import query_features_for_stories, QueryFeaturesInput

# Setup In-Memory DB for Benchmark
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL)

# Patch the engine used by the tool
import orchestrator_agent.agent_tools.product_user_story_tool.tools as target_module
import agile_sqlmodel
agile_sqlmodel.engine = test_engine
target_module.engine = test_engine # Just to be safe if it was already imported

def setup_data(num_themes=5, epics_per_theme=5, features_per_epic=10, stories_per_feature=5):
    print(f"Setting up data: {num_themes} Themes, {epics_per_theme} Epics/Theme, {features_per_epic} Features/Epic...")
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        product = Product(name="Benchmark Product")
        session.add(product)
        session.commit()
        session.refresh(product)

        for t in range(num_themes):
            theme = Theme(title=f"Theme {t}", product_id=product.product_id)
            session.add(theme)
            session.commit()
            session.refresh(theme)

            for e in range(epics_per_theme):
                epic = Epic(title=f"Epic {t}-{e}", theme_id=theme.theme_id)
                session.add(epic)
                session.commit()
                session.refresh(epic)

                features = []
                for f in range(features_per_epic):
                    feature = Feature(title=f"Feature {t}-{e}-{f}", epic_id=epic.epic_id)
                    features.append(feature)
                session.add_all(features)
                session.commit()

                for feature in features:
                    stories = []
                    for s in range(stories_per_feature):
                        story = UserStory(
                            title=f"Story {feature.feature_id}-{s}",
                            product_id=product.product_id,
                            feature_id=feature.feature_id
                        )
                        stories.append(story)
                    session.add_all(stories)
                session.commit()

        return product.product_id

def run_benchmark():
    product_id = setup_data(num_themes=5, epics_per_theme=5, features_per_epic=20, stories_per_feature=2)
    # Total features: 5 * 5 * 20 = 500 features.

    print("Starting Benchmark...")
    start_time = time.time()

    result = query_features_for_stories(QueryFeaturesInput(product_id=product_id))

    end_time = time.time()
    duration = end_time - start_time

    print(f"\nBenchmark Completed in {duration:.4f} seconds")
    print(f"Total Features Found: {result.get('total_features')}")

    # Validation of structure
    structure = result.get("structure", [])
    if structure:
        first_theme = structure[0]
        print(f"Theme keys: {list(first_theme.keys())}")
        if first_theme.get("epics"):
            first_epic = first_theme["epics"][0]
            print(f"Epic keys: {list(first_epic.keys())}")
            if first_epic.get("features"):
                first_feature = first_epic["features"][0]
                print(f"Feature keys: {list(first_feature.keys())}")
                print(f"Sibling features count: {len(first_feature.get('sibling_features', []))}")

if __name__ == "__main__":
    run_benchmark()
