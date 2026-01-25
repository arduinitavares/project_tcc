
import time
import sys
from pathlib import Path
from sqlmodel import Session, create_engine, SQLModel
from sqlalchemy import Engine, event

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator_agent.agent_tools.sprint_planning.tools import plan_sprint_tool, PlanSprintInput
from agile_sqlmodel import Product, UserStory, StoryStatus, Team, ProductTeam, Feature

# Setup in-memory DB for benchmarking
engine = create_engine("sqlite:///:memory:")
SQLModel.metadata.create_all(engine)

# Patch the engine in the tools module
import orchestrator_agent.agent_tools.sprint_planning.tools as sprint_tools
sprint_tools.engine = engine

def seed_database():
    with Session(engine) as session:
        # Create Products
        p1 = Product(name="Product A", description="Main product")
        session.add(p1)
        p2 = Product(name="Product B", description="Other product")
        session.add(p2)
        session.commit()
        session.refresh(p1)
        session.refresh(p2)

        # Create Team
        team = Team(name="Team Alpha")
        session.add(team)
        session.commit()
        session.refresh(team)

        # Link Team to Product A
        link = ProductTeam(product_id=p1.product_id, team_id=team.team_id)
        session.add(link)
        session.commit()

        # Create Feature for Product A (to test joinedload)
        f1 = Feature(title="Feature 1", description="Desc", epic_id=1) # epic_id doesn't exist but FKs might fail if enforced.
        # Actually agile_sqlmodel enforces FKs via PRAGMA, so I should probably be careful or just create structure properly.
        # But wait, Feature requires Epic. Epic requires Theme.
        # Let's create full hierarchy to be safe and test join performance.
        from agile_sqlmodel import Theme, Epic

        theme = Theme(title="Theme 1", product_id=p1.product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)

        epic = Epic(title="Epic 1", theme_id=theme.theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)

        feature = Feature(title="Feature 1", epic_id=epic.epic_id)
        session.add(feature)
        session.commit()
        session.refresh(feature)

        story_ids = []

        # 30 Valid Stories (Product A, TO_DO)
        for i in range(30):
            s = UserStory(
                title=f"Valid Story {i}",
                status=StoryStatus.TO_DO,
                product_id=p1.product_id,
                feature_id=feature.feature_id, # Link to feature to trigger join
                story_points=3
            )
            session.add(s)
            session.commit()
            session.refresh(s)
            story_ids.append(s.story_id)

        # 10 Wrong Product Stories (Product B, TO_DO)
        for i in range(10):
            s = UserStory(
                title=f"Wrong Product Story {i}",
                status=StoryStatus.TO_DO,
                product_id=p2.product_id,
                story_points=5
            )
            session.add(s)
            session.commit()
            session.refresh(s)
            story_ids.append(s.story_id)

        # 10 Wrong Status Stories (Product A, IN_PROGRESS)
        for i in range(10):
            s = UserStory(
                title=f"Wrong Status Story {i}",
                status=StoryStatus.IN_PROGRESS,
                product_id=p1.product_id,
                story_points=2
            )
            session.add(s)
            session.commit()
            session.refresh(s)
            story_ids.append(s.story_id)

        return p1.product_id, team.team_id, story_ids

def benchmark():
    product_id, team_id, all_story_ids = seed_database()

    # Add some non-existent IDs
    input_story_ids = all_story_ids + [9999, 10000]

    print(f"Benchmarking with {len(input_story_ids)} input stories ({len(all_story_ids)} existing).")

    # Reset query count
    query_count = 0

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1
        # Optional: Print statement to see what's happening (noisy)
        # print(f"QUERY: {statement}")

    plan_input = PlanSprintInput(
        product_id=product_id,
        team_id=team_id,
        sprint_goal="Benchmark Sprint",
        selected_story_ids=input_story_ids,
        duration_days=14
    )

    # Measure
    start_time = time.time()
    result = plan_sprint_tool(plan_input)
    end_time = time.time()

    duration = end_time - start_time

    print(f"\nExecution Time: {duration:.4f} seconds")
    print(f"Query Count: {query_count}")

    if not result["success"]:
        print("Error in plan_sprint_tool")
        print(result.get("error"))
        sys.exit(1)

    print(f"Result Stories: {len(result['draft']['validated_stories'])} valid, {len(result['warnings'] or [])} invalid.")

    # Validation
    # We expect 30 valid stories.
    # We expect 22 invalid (10 wrong prod, 10 wrong status, 2 not found)
    assert len(result['draft']['validated_stories']) == 30
    assert len(result['draft']['invalid_stories']) == 22
    print("Validation counts match expectations.")

if __name__ == "__main__":
    benchmark()
