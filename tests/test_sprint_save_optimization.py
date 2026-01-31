# pylint: disable=wrong-import-position, import-outside-toplevel, not-callable, missing-module-docstring, missing-function-docstring
import sys
from pathlib import Path
from sqlmodel import Session, select, func

# Adjust path to include project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from agile_sqlmodel import Product, Team, UserStory, Task, StoryStatus
from orchestrator_agent.agent_tools.sprint_planning.tools import SaveSprintInput, TaskBreakdown

def test_save_sprint_tasks_idempotency(engine):
    """
    Test that saving a sprint with tasks is idempotent:
    - First run creates tasks.
    - Second run with same tasks creates no duplicates.
    """
    # Patch the module's engine
    import orchestrator_agent.agent_tools.sprint_planning.tools as sprint_tools
    sprint_tools.engine = engine

    # Setup
    with Session(engine) as session:
        product = Product(name="Idempotency Product", description="Test")
        team = Team(name="Idempotency Team")
        session.add(product)
        session.add(team)
        session.commit()
        session.refresh(product)
        session.refresh(team)

        story = UserStory(
            product_id=product.product_id,
            title="Story 1",
            status=StoryStatus.TO_DO
        )
        session.add(story)
        session.commit()
        session.refresh(story)

        product_id = product.product_id
        team_id = team.team_id
        story_id = story.story_id

    # Input Data
    tasks = ["Task A", "Task B", "Task C"]
    input_data = SaveSprintInput(
        product_id=product_id,
        team_id=team_id,
        sprint_goal="Idempotency Goal",
        selected_story_ids=[story_id],
        start_date="2023-01-01",
        end_date="2023-01-14",
        task_breakdown=[TaskBreakdown(story_id=story_id, tasks=tasks)]
    )

    # Run 1: Create
    from orchestrator_agent.agent_tools.sprint_planning.tools import save_sprint_tool
    result1 = save_sprint_tool(input_data)

    assert result1["success"] is True
    assert result1["tasks_created"] == 3

    # Verify DB
    with Session(engine) as session:
        count = session.exec(
            select(func.count(Task.task_id)).where(Task.story_id == story_id)
        ).one()
        assert count == 3

    # Run 2: Idempotency (Same input)
    result2 = save_sprint_tool(input_data)

    assert result2["success"] is True
    assert result2["tasks_created"] == 0 # Should be 0

    # Verify DB count matches
    with Session(engine) as session:
        count = session.exec(
            select(func.count(Task.task_id)).where(Task.story_id == story_id)
        ).one()
        assert count == 3

def test_save_sprint_tasks_mixed_state(engine):
    """
    Test adding NEW tasks when some already exist.
    """
    import orchestrator_agent.agent_tools.sprint_planning.tools as sprint_tools
    sprint_tools.engine = engine

    # Setup
    with Session(engine) as session:
        product = Product(name="Mixed Product", description="Test")
        team = Team(name="Mixed Team")
        session.add(product)
        session.add(team)
        session.commit()
        session.refresh(product)
        session.refresh(team)

        story = UserStory(product_id=product.product_id, title="Story Mix", status=StoryStatus.TO_DO)
        session.add(story)
        session.commit()
        session.refresh(story)

        # Pre-create one task
        existing_task = Task(story_id=story.story_id, description="Existing Task")
        session.add(existing_task)
        session.commit()

        product_id = product.product_id
        team_id = team.team_id
        story_id = story.story_id

    # Input: 1 existing, 2 new
    tasks = ["Existing Task", "New Task 1", "New Task 2"]
    input_data = SaveSprintInput(
        product_id=product_id,
        team_id=team_id,
        sprint_goal="Mixed Goal",
        selected_story_ids=[story_id],
        start_date="2023-01-01",
        end_date="2023-01-14",
        task_breakdown=[TaskBreakdown(story_id=story_id, tasks=tasks)]
    )

    from orchestrator_agent.agent_tools.sprint_planning.tools import save_sprint_tool
    result = save_sprint_tool(input_data)

    assert result["success"] is True
    assert result["tasks_created"] == 2

    with Session(engine) as session:
        db_tasks = session.exec(select(Task).where(Task.story_id == story_id)).all()
        assert len(db_tasks) == 3
        descriptions = {t.description for t in db_tasks}
        assert "Existing Task" in descriptions
        assert "New Task 1" in descriptions
        assert "New Task 2" in descriptions

def test_save_sprint_multiple_stories(engine):
    """
    Test tasks across multiple stories.
    """
    import orchestrator_agent.agent_tools.sprint_planning.tools as sprint_tools
    sprint_tools.engine = engine

    with Session(engine) as session:
        product = Product(name="Multi Product", description="Test")
        team = Team(name="Multi Team")
        session.add(product)
        session.add(team)
        session.commit()
        session.refresh(product)
        session.refresh(team)

        s1 = UserStory(product_id=product.product_id, title="S1", status=StoryStatus.TO_DO)
        s2 = UserStory(product_id=product.product_id, title="S2", status=StoryStatus.TO_DO)
        session.add(s1)
        session.add(s2)
        session.commit()
        session.refresh(s1)
        session.refresh(s2)

        pid, tid, sid1, sid2 = product.product_id, team.team_id, s1.story_id, s2.story_id

    input_data = SaveSprintInput(
        product_id=pid,
        team_id=tid,
        sprint_goal="Multi Goal",
        selected_story_ids=[sid1, sid2],
        start_date="2023-01-01",
        end_date="2023-01-14",
        task_breakdown=[
            TaskBreakdown(story_id=sid1, tasks=["T1-A", "T1-B"]),
            TaskBreakdown(story_id=sid2, tasks=["T2-A"])
        ]
    )

    from orchestrator_agent.agent_tools.sprint_planning.tools import save_sprint_tool
    result = save_sprint_tool(input_data)

    assert result["success"] is True
    assert result["tasks_created"] == 3

    with Session(engine) as session:
        c1 = session.exec(select(func.count(Task.task_id)).where(Task.story_id == sid1)).one()
        c2 = session.exec(select(func.count(Task.task_id)).where(Task.story_id == sid2)).one()
        assert c1 == 2
        assert c2 == 1
