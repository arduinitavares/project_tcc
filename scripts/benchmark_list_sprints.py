import unittest
from datetime import date, timedelta
import sys
import os

from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

# Add repo root to path
sys.path.append(os.getcwd())

from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    StoryStatus,
    Team,
    UserStory,
)

# Import the function to be tested
from orchestrator_agent.agent_tools.sprint_planning import sprint_query_tools

class QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1

def setup_data(session, product_id):
    # Create 5 teams
    teams = []
    for i in range(5):
        team = Team(name=f"Team {i}")
        session.add(team)
        teams.append(team)
    session.commit()
    for team in teams:
        session.refresh(team)

    # Create 20 sprints (4 per team)
    sprints = []
    base_date = date(2024, 1, 1)
    for i in range(20):
        team = teams[i % 5]
        sprint = Sprint(
            goal=f"Sprint {i}",
            start_date=base_date + timedelta(days=i*14),
            end_date=base_date + timedelta(days=(i+1)*14 - 1),
            status=SprintStatus.ACTIVE,
            product_id=product_id,
            team_id=team.team_id,
        )
        session.add(sprint)
        sprints.append(sprint)
    session.commit()
    for sprint in sprints:
        session.refresh(sprint)

    # Create 50 stories distributed across sprints
    for i in range(50):
        story = UserStory(
            title=f"Story {i}",
            product_id=product_id,
            status=StoryStatus.TO_DO,
            story_points=3,
        )
        session.add(story)
        session.commit() # Get ID
        session.refresh(story)

        # Assign to a sprint
        sprint = sprints[i % 20]
        session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story.story_id))
    session.commit()

def run_benchmark():
    # Setup DB
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Enforce foreign keys
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)

    # Patch module engine
    sprint_query_tools.engine = engine

    # Setup data
    with Session(engine) as session:
        product = Product(name="Benchmark Product")
        session.add(product)
        session.commit()
        session.refresh(product)

        setup_data(session, product.product_id)
        product_id = product.product_id

    # Measure
    query_counter = QueryCounter()
    event.listen(engine, "before_cursor_execute", query_counter)

    print(f"Running list_sprints for product {product_id}...")
    result = sprint_query_tools.list_sprints(product_id)

    event.remove(engine, "before_cursor_execute", query_counter)

    print(f"Result success: {result.get('success')}")
    print(f"Sprints found: {len(result.get('sprints', []))}")
    print(f"Total queries executed: {query_counter.count}")

    return query_counter.count

if __name__ == "__main__":
    run_benchmark()
