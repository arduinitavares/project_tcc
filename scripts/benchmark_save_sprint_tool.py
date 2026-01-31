# pylint: disable=wrong-import-position, missing-module-docstring, missing-class-docstring, missing-function-docstring
import sys
import time
from pathlib import Path
from typing import Dict, Any
from sqlalchemy import event
from sqlmodel import Session, create_engine, SQLModel

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agile_sqlmodel import (
    Product, Team, UserStory, StoryStatus
)
from orchestrator_agent.agent_tools.sprint_planning.tools import (
    save_sprint_tool, SaveSprintInput, TaskBreakdown
)

class QueryCounter:
    def __init__(self, engine):
        self.engine = engine
        self.count = 0
        event.listen(engine, "before_cursor_execute", self.callback)

    # pylint: disable=unused-argument, too-many-arguments, too-many-positional-arguments
    def callback(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1

    def reset(self):
        self.count = 0

def setup_db():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine

def seed_data(session: Session, num_stories: int) -> Dict[str, Any]:
    # Create Product
    product = Product(name="Benchmark Product", description="For testing")
    session.add(product)

    # Create Team
    team = Team(name="Benchmark Team")
    session.add(team)

    session.commit()
    session.refresh(product)
    session.refresh(team)

    # Create Stories
    story_ids = []
    for i in range(num_stories):
        story = UserStory(
            product_id=product.product_id,
            title=f"Story {i}",
            status=StoryStatus.TO_DO,
            story_points=3
        )
        session.add(story)
        session.commit()
        session.refresh(story)
        story_ids.append(story.story_id)

    return {
        "product_id": product.product_id,
        "team_id": team.team_id,
        "story_ids": story_ids
    }

def run_benchmark(label: str, num_stories: int, tasks_per_story: int):
    print(f"\n--- Benchmark: {label} ({num_stories} stories, {tasks_per_story} tasks/story) ---")

    # Setup fresh DB
    engine = setup_db()

    # Patch the tool's engine
    # pylint: disable=import-outside-toplevel
    import orchestrator_agent.agent_tools.sprint_planning.tools as sprint_tools
    sprint_tools.engine = engine

    with Session(engine) as session:
        data = seed_data(session, num_stories)

    # Prepare Input
    task_breakdown = []
    for story_id in data["story_ids"]:
        tasks = [f"Task {j} for Story {story_id}" for j in range(tasks_per_story)]
        task_breakdown.append(TaskBreakdown(story_id=story_id, tasks=tasks))

    input_data = SaveSprintInput(
        product_id=data["product_id"],
        team_id=data["team_id"],
        sprint_goal="Benchmark Sprint",
        selected_story_ids=data["story_ids"],
        start_date="2023-01-01",
        end_date="2023-01-14",
        task_breakdown=task_breakdown
    )

    # Attach Query Counter
    counter = QueryCounter(engine)

    # Run Tool
    start_time = time.time()
    result = save_sprint_tool(input_data)
    end_time = time.time()

    duration = end_time - start_time

    print(f"Success: {result.get('success')}")
    print(f"Time: {duration:.4f}s")
    print(f"Queries: {counter.count}")
    print(f"Tasks Created: {result.get('tasks_created')}")

    return {
        "label": label,
        "stories": num_stories,
        "total_tasks": num_stories * tasks_per_story,
        "time": duration,
        "queries": counter.count
    }

if __name__ == "__main__":
    results = []

    # Typical Load
    results.append(run_benchmark("Typical Load", num_stories=10, tasks_per_story=5))

    # Stress Load
    results.append(run_benchmark("Stress Load", num_stories=50, tasks_per_story=5))

    print("\n--- Summary ---")
    print(f"{'Scenario':<15} | {'Tasks':<10} | {'Time (s)':<10} | {'Queries':<10}")
    print("-" * 55)
    for r in results:
        print(f"{r['label']:<15} | {r['total_tasks']:<10} | {r['time']:<10.4f} | {r['queries']:<10}")
