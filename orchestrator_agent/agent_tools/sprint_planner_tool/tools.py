"""Tools for the Sprint Planner agent."""

import json
import re
from datetime import date, timedelta
import time
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
from utils.schemes import ValidationEvidence
from utils.task_metadata import metadata_from_structured_task, serialize_task_metadata

from .schemes import (
    SprintPlannerOutput,
    validate_task_decomposition_quality,
    validate_task_invariant_bindings,
)


class SaveSprintPlanInput(BaseModel):
    """Input schema for save_sprint_plan_tool."""

    product_id: Annotated[int, Field(description="Product ID for the sprint.")]
    team_id: Annotated[Optional[int], Field(default=None, description="Team ID owning the sprint. Required if team_name is not provided.")]
    team_name: Annotated[Optional[str], Field(default=None, description="Team name to lookup or create. Used if team_id is not provided.")]
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
    *,
    ignore_sprint_id: Optional[int] = None,
) -> List[int]:
    """Return story IDs already assigned to active or planned sprints."""

    if not story_ids:
        return []

    query = (
        select(SprintStory.story_id)
        .join(Sprint, col(Sprint.sprint_id) == col(SprintStory.sprint_id))
        .where(
            col(SprintStory.story_id).in_(story_ids),
            col(Sprint.status).in_([SprintStatus.PLANNED, SprintStatus.ACTIVE]),
        )
    )
    if ignore_sprint_id is not None:
        query = query.where(col(Sprint.sprint_id) != ignore_sprint_id)

    existing = session.exec(query).all()

    return list({row for row in existing})


def _coerce_duration_seconds(value: Any) -> Optional[float]:
    """Return a non-negative float duration or None when value is invalid."""
    if value is None:
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if duration < 0:
        return None
    return duration


def _normalize_acceptance_criteria(text: Optional[str]) -> List[str]:
    """Normalize story acceptance criteria using the canonical API behavior."""

    if not text or not text.strip():
        return []

    items: List[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        normalized = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", stripped).strip()
        if normalized:
            items.append(normalized)

    if items:
        return items

    collapsed = " ".join(text.split())
    return [collapsed] if collapsed else []


def _story_allowed_invariant_ids(story: UserStory) -> List[str]:
    """Return invariant IDs a task may bind for a given story."""

    if not story.validation_evidence:
        return []
    try:
        evidence = ValidationEvidence.model_validate_json(story.validation_evidence)
    except Exception:  # pylint: disable=broad-except
        return []
    return list(evidence.evaluated_invariant_ids or [])


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

    start_ts = time.perf_counter()
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

        # Resolve Team
        team = None
        if input_data.team_id:
            team = session.exec(
                select(Team).where(Team.team_id == input_data.team_id)
            ).first()
            if not team:
                return {
                    "success": False,
                    "error": f"Team {input_data.team_id} not found.",
                }
        elif input_data.team_name:
            # Lookup by name
            team = session.exec(
                select(Team).where(Team.name == input_data.team_name)
            ).first()
            # Auto-create if not found
            if not team:
                team = Team(name=input_data.team_name)
                session.add(team)
                session.commit()
                session.refresh(team)
        else:
            return {
                "success": False,
                "error": "Either team_id or team_name must be provided.",
            }

        existing_planned_sprint = session.exec(
            select(Sprint)
            .where(
                Sprint.product_id == input_data.product_id,
                Sprint.status == SprintStatus.PLANNED,
            )
            .order_by(Sprint.updated_at.desc(), Sprint.sprint_id.desc())
        ).first()

        story_ids = [story.story_id for story in validated_plan.selected_stories]
        conflicts = _get_story_conflicts(
            session,
            story_ids,
            ignore_sprint_id=existing_planned_sprint.sprint_id
            if existing_planned_sprint and existing_planned_sprint.sprint_id is not None
            else None,
        )
        if conflicts:
            return {
                "success": False,
                "error_code": "STORY_ALREADY_IN_OPEN_SPRINT",
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

        allowed_invariant_ids_by_story = {
            int(story.story_id): _story_allowed_invariant_ids(story)
            for story in stories
            if story.story_id is not None
        }
        binding_errors = validate_task_invariant_bindings(
            validated_plan,
            allowed_invariant_ids_by_story=allowed_invariant_ids_by_story,
        )
        if binding_errors:
            return {
                "success": False,
                "error": "Sprint plan validation error: " + "; ".join(binding_errors),
            }

        include_task_decomposition = True
        sprint_input_dict = tool_context.state.get("sprint_input", {})
        if isinstance(sprint_input_dict, dict) and "include_task_decomposition" in sprint_input_dict:
            include_task_decomposition = bool(sprint_input_dict["include_task_decomposition"])

        has_ac_by_story = {
            int(story.story_id): bool((story.acceptance_criteria or "").strip())
            for story in stories
            if story.story_id is not None
        }
        acceptance_criteria_items_by_story = {
            int(story.story_id): _normalize_acceptance_criteria(story.acceptance_criteria)
            for story in stories
            if story.story_id is not None
        }
        decomposition_errors = validate_task_decomposition_quality(
            validated_plan,
            include_task_decomposition=include_task_decomposition,
            has_acceptance_criteria_by_story=has_ac_by_story,
            acceptance_criteria_items_by_story=acceptance_criteria_items_by_story,
        )
        if decomposition_errors:
            return {
                "success": False,
                "error": "Decomposition quality checks failed: " + "; ".join(decomposition_errors),
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
        sprint = existing_planned_sprint
        if sprint is None:
            sprint = Sprint(
                goal=validated_plan.sprint_goal,
                start_date=start_date,
                end_date=end_date,
                status=SprintStatus.PLANNED,
                started_at=None,
                product_id=input_data.product_id,
                team_id=team.team_id,
            )
            session.add(sprint)
            session.flush()
        else:
            sprint.goal = validated_plan.sprint_goal
            sprint.start_date = start_date
            sprint.end_date = end_date
            sprint.team_id = team.team_id
            sprint.status = SprintStatus.PLANNED
            sprint.started_at = None
            sprint.completed_at = None
            session.add(sprint)
            existing_links = session.exec(
                select(SprintStory).where(SprintStory.sprint_id == sprint.sprint_id)
            ).all()
            for link in existing_links:
                session.delete(link)
            session.flush()

        if sprint.sprint_id is None:
            raise RuntimeError("Sprint ID was not generated.")

        existing_tasks_by_story: Dict[int, Dict[str, List[Task]]] = {}
        for task in session.exec(
            select(Task)
            .where(col(Task.story_id).in_(story_ids))
            .order_by(Task.story_id, Task.task_id)
        ).all():
            story_task_map = existing_tasks_by_story.setdefault(task.story_id, {})
            story_task_map.setdefault(task.description, []).append(task)

        for story in validated_plan.selected_stories:
            session.add(
                SprintStory(sprint_id=sprint.sprint_id, story_id=story.story_id)
            )
            story_tasks = existing_tasks_by_story.get(story.story_id, {})
            desired_descriptions = {task_spec.description for task_spec in story.tasks}

            for description, duplicate_tasks in story_tasks.items():
                if description in desired_descriptions:
                    for duplicate_task in duplicate_tasks[1:]:
                        session.delete(duplicate_task)
                else:
                    for obsolete_task in duplicate_tasks:
                        session.delete(obsolete_task)

            for task_spec in story.tasks:
                metadata_json = serialize_task_metadata(
                    metadata_from_structured_task(task_spec)
                )
                matching_tasks = story_tasks.get(task_spec.description, [])
                if matching_tasks:
                    kept_task = matching_tasks[0]
                    kept_task.metadata_json = metadata_json
                    session.add(kept_task)
                    story_tasks[task_spec.description] = [kept_task]
                else:
                    new_task = Task(
                        story_id=story.story_id,
                        description=task_spec.description,
                        metadata_json=metadata_json,
                    )
                    session.add(new_task)
                    story_tasks[task_spec.description] = [new_task]

        event_metadata = json.dumps(
            {
                "sprint_goal": validated_plan.sprint_goal,
                "sprint_number": validated_plan.sprint_number,
                "selected_story_ids": story_ids,
                "capacity_analysis": validated_plan.capacity_analysis.model_dump(),
            }
        )
        # Prefer orchestrator-provided duration when present and valid.
        duration_seconds: Optional[float] = None
        if tool_context and tool_context.state:
            duration_seconds = _coerce_duration_seconds(
                tool_context.state.get("sprint_planning_duration")
            )
        if duration_seconds is None:
            duration_seconds = round(time.perf_counter() - start_ts, 3)
        session_id = getattr(tool_context, "session_id", None)

        session.add(
            WorkflowEvent(
                event_type=WorkflowEventType.SPRINT_PLAN_SAVED,
                product_id=input_data.product_id,
                sprint_id=sprint.sprint_id,
                session_id=session_id,
                event_metadata=event_metadata,
                duration_seconds=float(duration_seconds),
            )
        )

        session.commit()

        return {
            "success": True,
            "sprint_id": sprint.sprint_id,
            "product_id": input_data.product_id,
            "team_id": team.team_id,
            "team_name": team.name,
            "selected_story_count": len(story_ids),
            "message": "Sprint plan saved successfully.",
        }


__all__ = ["SaveSprintPlanInput", "save_sprint_plan_tool"]
