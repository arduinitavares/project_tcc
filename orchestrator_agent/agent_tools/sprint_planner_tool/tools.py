"""Tools for the Sprint Planner agent."""

import json
from datetime import date, timedelta
from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, col, select

from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    Task,
    Team,
    UserStory,
    WorkflowEvent,
    WorkflowEventType,
    get_engine,
)

from .schemes import SprintPlannerOutput


class SaveSprintPlanInput(BaseModel):
    """Input schema for save_sprint_plan_tool."""

    product_id: Annotated[int, Field(description="Product ID for the sprint.")]
    team_id: Annotated[int, Field(description="Team ID owning the sprint.")]
    sprint_start_date: Annotated[str, Field(description="Sprint start date (YYYY-MM-DD).")]
    sprint_duration_days: Annotated[
        int,
        Field(
            default=14,
            description="Sprint duration in days (default 14, min 1, max 31).",
        ),
    ]


def _get_story_conflicts(
    session: Session,
    story_ids: List[int],
) -> List[int]:
    """Return story IDs already assigned to active or planned sprints."""

    if not story_ids:
        return []

    existing = session.exec(
        select(SprintStory.story_id)
        .join(Sprint, col(Sprint.sprint_id) == col(SprintStory.sprint_id))
        .where(
            col(SprintStory.story_id).in_(story_ids),
            col(Sprint.status).in_([SprintStatus.PLANNED, SprintStatus.ACTIVE]),
        )
    ).all()

    return list({row for row in existing})


def save_sprint_plan_tool(
    input_data: SaveSprintPlanInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Persist an approved sprint plan to the database.

    Reads the sprint plan from ToolContext state under key 'sprint_plan',
    validates it against SprintPlannerOutput, and persists Sprint, SprintStory,
    and Task records.
    """
    if not tool_context:
        return {
            "success": False,
            "error": "ToolContext required for sprint plan persistence.",
        }

    sprint_plan = tool_context.state.get("sprint_plan")
    if not sprint_plan:
        return {
            "success": False,
            "error": "No sprint plan found in session state.",
        }

    try:
        validated_plan = SprintPlannerOutput.model_validate(sprint_plan)
    except ValidationError as exc:
        return {
            "success": False,
            "error": f"Sprint plan validation error: {exc}",
        }

    engine = get_engine()

    with Session(engine) as session:
        product = session.exec(
            select(Product).where(Product.product_id == input_data.product_id)
        ).first()
        if not product:
            return {
                "success": False,
                "error": f"Product {input_data.product_id} not found.",
            }

        team = session.exec(
            select(Team).where(Team.team_id == input_data.team_id)
        ).first()
        if not team:
            return {
                "success": False,
                "error": f"Team {input_data.team_id} not found.",
            }

        story_ids = [story.story_id for story in validated_plan.selected_stories]
        conflicts = _get_story_conflicts(session, story_ids)
        if conflicts:
            return {
                "success": False,
                "error": (
                    "Stories already assigned to active or planned sprints: "
                    f"{sorted(conflicts)}"
                ),
            }

        stories = session.exec(
            select(UserStory).where(col(UserStory.story_id).in_(story_ids))
        ).all()
        found_story_ids = {story.story_id for story in stories}
        missing_story_ids = sorted(set(story_ids) - found_story_ids)
        if missing_story_ids:
            return {
                "success": False,
                "error": f"Stories not found: {missing_story_ids}",
            }

        mismatched_product_ids = [
            story.story_id
            for story in stories
            if story.product_id != input_data.product_id and story.story_id is not None
        ]
        if mismatched_product_ids:
            return {
                "success": False,
                "error": (
                    "Stories not linked to product "
                    f"{input_data.product_id}: {sorted(mismatched_product_ids)}"
                ),
            }

        try:
            start_date = date.fromisoformat(input_data.sprint_start_date)
        except ValueError:
            return {
                "success": False,
                "error": (
                    f"Invalid date format: {input_data.sprint_start_date}. "
                    "Use YYYY-MM-DD."
                ),
            }

        end_date = start_date + timedelta(days=input_data.sprint_duration_days)
        sprint = Sprint(
            goal=validated_plan.sprint_goal,
            start_date=start_date,
            end_date=end_date,
            status=SprintStatus.PLANNED,
            product_id=input_data.product_id,
            team_id=input_data.team_id,
        )
        session.add(sprint)
        session.flush()

        if sprint.sprint_id is None:
            raise RuntimeError("Sprint ID was not generated.")

        for story in validated_plan.selected_stories:
            session.add(
                SprintStory(sprint_id=sprint.sprint_id, story_id=story.story_id)
            )
            for task_description in story.tasks:
                session.add(
                    Task(story_id=story.story_id, description=task_description)
                )

        event_metadata = json.dumps(
            {
                "sprint_goal": validated_plan.sprint_goal,
                "sprint_number": validated_plan.sprint_number,
                "selected_story_ids": story_ids,
                "capacity_analysis": validated_plan.capacity_analysis.model_dump(),
            }
        )
        session.add(
            WorkflowEvent(
                event_type=WorkflowEventType.SPRINT_PLAN_SAVED,
                product_id=input_data.product_id,
                sprint_id=sprint.sprint_id,
                event_metadata=event_metadata,
            )
        )

        session.commit()

        return {
            "success": True,
            "sprint_id": sprint.sprint_id,
            "product_id": input_data.product_id,
            "team_id": input_data.team_id,
            "selected_story_count": len(story_ids),
            "message": "Sprint plan saved successfully.",
        }


__all__ = ["SaveSprintPlanInput", "save_sprint_plan_tool"]
