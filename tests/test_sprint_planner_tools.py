"""Tests for sprint planner persistence tool."""

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, cast

from google.adk.tools import ToolContext
from sqlmodel import Session, select

from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    Task,
    Team,
    UserStory,
)
from orchestrator_agent.agent_tools.sprint_planner_tool.tools import (
    SaveSprintPlanInput,
    save_sprint_plan_tool,
)


def _seed_product_team_stories(session: Session) -> tuple[int, int, List[int]]:
    product = Product(name="Test Product", vision="Vision", description="Desc")
    team = Team(name="Team Alpha")
    session.add(product)
    session.add(team)
    session.commit()
    session.refresh(product)
    session.refresh(team)

    assert product.product_id is not None
    assert team.team_id is not None

    stories: List[int] = []
    for idx in range(2):
        story = UserStory(
            product_id=product.product_id,
            title=f"Story {idx + 1}",
            story_description="As a user, I want...",
            acceptance_criteria="- AC",
        )
        session.add(story)
        session.flush()
        assert story.story_id is not None
        stories.append(story.story_id)

    session.commit()
    return product.product_id, team.team_id, stories


def _build_sprint_plan(story_ids: List[int]) -> Dict[str, Any]:
    return {
        "sprint_goal": "Deliver authentication essentials",
        "sprint_number": 1,
        "duration_days": 14,
        "selected_stories": [
            {
                "story_id": story_ids[0],
                "story_title": "Story 1",
                "tasks": ["Create auth table", "Add login UI"],
                "reason_for_selection": "Core to sprint goal",
            }
        ],
        "deselected_stories": [
            {"story_id": story_ids[1], "reason": "Does not fit capacity"}
        ],
        "capacity_analysis": {
            "velocity_assumption": "Medium",
            "capacity_band": "4-5 stories",
            "selected_count": 1,
            "story_points_used": 3,
            "max_story_points": 10,
            "commitment_note": "Does this scope feel achievable in 2 weeks?",
            "reasoning": "Scope fits capacity band.",
        },
    }


def test_save_sprint_plan_creates_records(session: Session):
    """Ensure sprint plan persistence creates sprint, links, and tasks."""
    product_id, team_id, story_ids = _seed_product_team_stories(session)

    tool_context = cast(
        ToolContext,
        SimpleNamespace(state={"sprint_plan": _build_sprint_plan(story_ids)}),
    )
    input_data = SaveSprintPlanInput(
        product_id=product_id,
        team_id=team_id,
        sprint_start_date="2026-02-01",
        sprint_duration_days=14,
    )

    result = save_sprint_plan_tool(input_data, tool_context)
    assert result["success"] is True

    sprint = session.exec(select(Sprint)).first()
    assert sprint is not None
    assert sprint.goal == "Deliver authentication essentials"

    links = session.exec(select(SprintStory)).all()
    assert len(links) == 1

    tasks = session.exec(select(Task)).all()
    assert len(tasks) == 2


def test_save_sprint_plan_rejects_story_conflict(session: Session):
    """Ensure a story cannot be assigned to multiple planned sprints."""
    product_id, team_id, story_ids = _seed_product_team_stories(session)

    existing_sprint = Sprint(
        goal="Existing sprint",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 14),
        status=SprintStatus.PLANNED,
        product_id=product_id,
        team_id=team_id,
    )
    session.add(existing_sprint)
    session.flush()
    assert existing_sprint.sprint_id is not None
    session.add(
        SprintStory(sprint_id=existing_sprint.sprint_id, story_id=story_ids[0])
    )
    session.commit()

    tool_context = cast(
        ToolContext,
        SimpleNamespace(state={"sprint_plan": _build_sprint_plan(story_ids)}),
    )
    input_data = SaveSprintPlanInput(
        product_id=product_id,
        team_id=team_id,
        sprint_start_date="2026-02-01",
        sprint_duration_days=14,
    )

    result = save_sprint_plan_tool(input_data, tool_context)
    assert result["success"] is False
    assert "Stories already assigned" in result["error"]
