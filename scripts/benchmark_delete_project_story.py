import asyncio
import os
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime

# Ensure we can import from the root of the project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set isolated DB targets before imports that might initialize them
temp_db_path = tempfile.mktemp(suffix=".db")
temp_session_db_path = tempfile.mktemp(suffix="_session.db")
os.environ["PROJECT_TCC_DB_URL"] = f"sqlite:///{temp_db_path}"
os.environ["PROJECT_TCC_SESSION_DB_URL"] = f"sqlite:///{temp_session_db_path}"

from sqlmodel import Session, SQLModel, select  # noqa: E402

import api  # noqa: E402
from agile_sqlmodel import (  # noqa: E402
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    StoryCompletionLog,
    StoryStatus,
    Task,
    TaskExecutionLog,
    TaskStatus,
    UserStory,
    get_engine,
)
from models.core import Team


def setup_data(session, num_stories=100, num_sprints=5, num_logs=3, num_tasks=5):
    # Create product
    product = Product(name=f"Bench Product {uuid.uuid4()}", description="Bench")
    session.add(product)
    session.commit()
    session.refresh(product)

    # Create unique team
    team = Team(name=f"Bench Team {uuid.uuid4()}")
    session.add(team)
    session.commit()
    session.refresh(team)

    # Create Sprints
    sprints = []
    now = datetime.now(UTC)
    for _ in range(num_sprints):
        s = Sprint(
            product_id=product.product_id,
            team_id=team.team_id,
            start_date=now,
            end_date=now,
            status=SprintStatus.PLANNED,
        )
        session.add(s)
        sprints.append(s)
    session.commit()
    for s in sprints:
        session.refresh(s)

    parent_req = f"bench-req-{uuid.uuid4()}"

    stories = []
    sprint_mappings = []
    logs = []
    tasks = []
    task_execution_logs = []

    # Create Stories
    for i in range(num_stories):
        story = UserStory(
            product_id=product.product_id,
            title=f"Story {i}",
            source_requirement=parent_req,
            status=StoryStatus.TO_DO,
        )
        stories.append(story)

    session.add_all(stories)
    session.commit()
    for s in stories:
        session.refresh(s)

    # Create Mappings, Logs, Tasks, and Task Execution Logs
    for story in stories:
        for s in sprints[:2]:  # add to 2 sprints
            sm = SprintStory(sprint_id=s.sprint_id, story_id=story.story_id)
            sprint_mappings.append(sm)

        for _ in range(num_logs):
            log = StoryCompletionLog(
                story_id=story.story_id,
                old_status=StoryStatus.TO_DO,
                new_status=StoryStatus.IN_PROGRESS,
            )
            logs.append(log)

        for _ in range(num_tasks):
            t = Task(
                story_id=story.story_id,
                description="Task",
                status=TaskStatus.TO_DO,
            )
            tasks.append(t)

    session.add_all(sprint_mappings)
    session.add_all(logs)
    session.add_all(tasks)
    session.commit()
    for t in tasks:
        session.refresh(t)

    # Add Task Execution Logs for tasks
    for t in tasks:
        t_log = TaskExecutionLog(
            task_id=t.task_id,
            sprint_id=sprints[0].sprint_id,
            new_status=TaskStatus.IN_PROGRESS,
        )
        task_execution_logs.append(t_log)

    session.add_all(task_execution_logs)
    session.commit()

    return product.product_id, parent_req


async def run_benchmark():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        product_id, parent_req = setup_data(
            session, num_stories=500, num_sprints=2, num_logs=2, num_tasks=5
        )

    print(f"Set up benchmark data. Product ID: {product_id}, Requirement: {parent_req}")

    start_time = time.time()
    await api.delete_project_story(product_id, parent_req)
    end_time = time.time()

    duration = end_time - start_time
    print(f"Deletion took {duration:.4f} seconds")

    with Session(engine) as session:
        remaining_stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()
        print(f"Remaining stories: {len(remaining_stories)}")

    # Clean up temp databases
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)
    if os.path.exists(temp_session_db_path):
        os.remove(temp_session_db_path)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
