
import time
import sys
import os
from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import db_tools
from agile_sqlmodel import Product

# Setup in-memory DB
DB_URL = "sqlite:///:memory:"
engine = create_engine(DB_URL, echo=False)

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SQLModel.metadata.create_all(engine)

# Patch the engine in db_tools
db_tools.engine = engine

def generate_roadmap_data(num_themes=5, epics_per_theme=5, features_per_epic=5):
    roadmap = []
    for t in range(num_themes):
        theme = {
            "quarter": "Q1",
            "theme_title": f"Theme {t}",
            "theme_description": f"Description for Theme {t}",
            "epics": []
        }
        for e in range(epics_per_theme):
            epic = {
                "epic_title": f"Epic {t}-{e}",
                "epic_summary": f"Summary for Epic {t}-{e}",
                "features": []
            }
            for f in range(features_per_epic):
                feature = {
                    "title": f"Feature {t}-{e}-{f}",
                    "description": f"Desc for Feature {t}-{e}-{f}"
                }
                epic["features"].append(feature)
            theme["epics"].append(epic)
        roadmap.append(theme)
    return roadmap

def run_benchmark():
    # create product
    with Session(engine) as session:
        product = Product(name="Benchmark Product", vision="Speed")
        session.add(product)
        session.commit()
        session.refresh(product)
        product_id = product.product_id

    # generate data
    # Increase load to make the difference obvious
    # 10 * 10 * 10 = 1000 features + 100 epics + 10 themes = 1110 objects
    data = generate_roadmap_data(num_themes=10, epics_per_theme=10, features_per_epic=10)

    print(f"Benchmarking persist_roadmap with {len(data)} themes, {len(data)*10} epics, {len(data)*10*10} features...")

    start_time = time.time()
    result = db_tools.persist_roadmap(product_id, data)
    end_time = time.time()

    duration = end_time - start_time

    if result["success"]:
        print(f"Success! Duration: {duration:.4f} seconds")
        print(result["message"])
    else:
        print(f"Failed: {result}")

    return duration

if __name__ == "__main__":
    run_benchmark()
