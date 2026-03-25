import time
import uuid
import sys
from datetime import datetime, timezone
from sqlmodel import Session, select, create_engine, SQLModel
from agile_sqlmodel import get_engine, Product, UserStory, SprintStory, Sprint, StoryCompletionLog, Task, TaskStatus, StoryStatus, SprintStatus, Team
from repositories.product import ProductRepository
import api
import asyncio

def setup_data(session, num_stories=100, num_sprints=5, num_logs=3, num_tasks=5):
    # Create product
    product = Product(name=f"Bench Product {uuid.uuid4()}", description="Bench")
    session.add(product)
    session.commit()
    session.refresh(product)

    team = Team(name="Bench Team")
    session.add(team)
    session.commit()
    session.refresh(team)

    # Create Sprints
    sprints = []
    now = datetime.now(timezone.utc)
    for _ in range(num_sprints):
        s = Sprint(product_id=product.product_id, team_id=team.team_id, start_date=now, end_date=now, status=SprintStatus.PLANNED)
        session.add(s)
        sprints.append(s)
    session.commit()
    for s in sprints:
        session.refresh(s)

    parent_req = "bench-req"

    stories = []
    sprint_mappings = []
    logs = []
    tasks = []

    # Create Stories
    for i in range(num_stories):
        story = UserStory(
            product_id=product.product_id,
            title=f"Story {i}",
            source_requirement=parent_req,
            status=StoryStatus.TO_DO
        )
        stories.append(story)

    session.add_all(stories)
    session.commit()
    for s in stories:
        session.refresh(s)

    # Create Mappings, Logs, Tasks
    for story in stories:
        for s in sprints[:2]: # add to 2 sprints
            sm = SprintStory(sprint_id=s.sprint_id, story_id=story.story_id)
            sprint_mappings.append(sm)

        for _ in range(num_logs):
            log = StoryCompletionLog(story_id=story.story_id, old_status=StoryStatus.TO_DO, new_status=StoryStatus.IN_PROGRESS)
            logs.append(log)

        for _ in range(num_tasks):
            t = Task(story_id=story.story_id, description="Task", status=TaskStatus.TO_DO)
            tasks.append(t)

    session.add_all(sprint_mappings)
    session.add_all(logs)
    session.add_all(tasks)
    session.commit()

    return product.product_id, parent_req

async def run_benchmark():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        product_id, parent_req = setup_data(session, num_stories=500, num_sprints=2, num_logs=2, num_tasks=5)

    print(f"Set up benchmark data. Product ID: {product_id}, Requirement: {parent_req}")

    start_time = time.time()
    await api.delete_project_story(product_id, parent_req)
    end_time = time.time()

    duration = end_time - start_time
    print(f"Deletion took {duration:.4f} seconds")

    with Session(engine) as session:
        remaining_stories = session.exec(select(UserStory).where(UserStory.product_id == product_id)).all()
        print(f"Remaining stories: {len(remaining_stories)}")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
