# orchestrator_agent/agent_tools/sprint_planning/tools.py
"""
Sprint Planning Tools for Scrum Master MVP.

Tools:
1. get_backlog_for_planning - Query backlog-ready stories for a product
2. plan_sprint_tool - Draft a sprint plan (goal, stories, capacity)
3. save_sprint_tool - Persist sprint (idempotent) with metrics capture
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    StoryStatus,
    Task,
    Team,
    UserStory,
    WorkflowEvent,
    WorkflowEventType,
    engine,
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return _utc_now().isoformat().replace("+00:00", "Z")


def _emit_workflow_event(
    session: Session,
    event_type: WorkflowEventType,
    product_id: Optional[int] = None,
    sprint_id: Optional[int] = None,
    session_id: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    turn_count: Optional[int] = None,
    event_metadata: Optional[Dict[str, Any]] = None,
) -> WorkflowEvent:
    """Create and persist a workflow event for metrics."""
    event = WorkflowEvent(
        event_type=event_type,
        product_id=product_id,
        sprint_id=sprint_id,
        session_id=session_id,
        duration_seconds=duration_seconds,
        turn_count=turn_count,
        event_metadata=json.dumps(event_metadata) if event_metadata else None,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


# =============================================================================
# SCHEMAS
# =============================================================================


class BacklogQueryInput(BaseModel):
    """Input schema for get_backlog_for_planning tool."""

    product_id: Annotated[int, Field(description="The product ID to query backlog for.")]
    only_ready: Annotated[
        bool,
        Field(
            default=True,
            description="If True, only return stories with status TO_DO (backlog-ready).",
        ),
    ]


class SprintStorySelection(BaseModel):
    """A single story selected for the sprint."""

    story_id: int
    title: str
    story_points: Optional[int] = None
    feature_title: Optional[str] = None


class TaskBreakdown(BaseModel):
    """A task breakdown for a story."""

    story_id: int
    tasks: List[str]


class PlanSprintInput(BaseModel):
    """Input schema for plan_sprint_tool."""

    product_id: Annotated[int, Field(description="The product ID for the sprint.")]
    team_id: Annotated[
        Optional[int],
        Field(default=None, description="Optional team ID. If not provided, uses first team linked to product."),
    ]
    sprint_goal: Annotated[
        str,
        Field(description="The sprint goal describing what the team commits to achieve."),
    ]
    selected_story_ids: Annotated[
        List[int],
        Field(description="List of story IDs selected for the sprint."),
    ]
    start_date: Annotated[
        Optional[str],
        Field(default=None, description="Sprint start date (YYYY-MM-DD). Defaults to today."),
    ]
    duration_days: Annotated[
        int,
        Field(default=14, description="Sprint duration in days. Default is 14 (2 weeks)."),
    ]
    capacity_points: Annotated[
        Optional[int],
        Field(default=None, description="Team capacity in story points for this sprint."),
    ]
    task_breakdown: Annotated[
        Optional[List[TaskBreakdown]],
        Field(default=None, description="Optional task breakdown for stories."),
    ]


class SaveSprintInput(BaseModel):
    """Input schema for save_sprint_tool (idempotent save)."""

    product_id: Annotated[int, Field(description="The product ID.")]
    team_id: Annotated[int, Field(description="The team ID.")]
    sprint_goal: Annotated[str, Field(description="The sprint goal.")]
    selected_story_ids: Annotated[List[int], Field(description="Story IDs for the sprint.")]
    start_date: Annotated[str, Field(description="Sprint start date (YYYY-MM-DD).")]
    end_date: Annotated[str, Field(description="Sprint end date (YYYY-MM-DD).")]
    task_breakdown: Annotated[
        Optional[List[TaskBreakdown]],
        Field(default=None, description="Optional tasks to create."),
    ]
    # Metrics for TCC
    planning_turn_count: Annotated[
        Optional[int],
        Field(default=None, description="Number of conversation turns during planning."),
    ]
    planning_start_time: Annotated[
        Optional[str],
        Field(default=None, description="ISO timestamp when planning started."),
    ]


# =============================================================================
# TOOL 1: GET BACKLOG FOR PLANNING
# =============================================================================


def get_backlog_for_planning(
    query_input: BacklogQueryInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Query backlog-ready stories for sprint planning.

    Returns stories that are:
    - Linked to the specified product
    - In TO_DO status (backlog-ready)
    - Optionally filtered to only validated stories

    Stories are grouped by theme/epic for easier planning.
    """
    # Handle dict input from ADK
    if isinstance(query_input, dict):
        query_input = BacklogQueryInput(**query_input)

    print(f"\n[Tool: get_backlog_for_planning] Querying product {query_input.product_id}...")

    try:
        with Session(engine) as session:
            # Verify product exists
            product = session.get(Product, query_input.product_id)
            if not product:
                return {
                    "success": False,
                    "error": f"Product {query_input.product_id} not found.",
                }

            # Query stories
            stmt = select(UserStory).where(
                UserStory.product_id == query_input.product_id
            )
            if query_input.only_ready:
                stmt = stmt.where(UserStory.status == StoryStatus.TO_DO)

            stories = list(session.exec(stmt).all())

            # Build response with capacity info
            total_points = sum(s.story_points or 0 for s in stories)
            stories_with_points = sum(1 for s in stories if s.story_points)

            stories_data: List[Dict[str, Any]] = []
            for story in stories:
                # Get feature info if available
                feature_title = None
                theme_title = None
                if story.feature:
                    feature_title = story.feature.title
                    if story.feature.epic and story.feature.epic.theme:
                        theme_title = story.feature.epic.theme.title

                stories_data.append({
                    "story_id": story.story_id,
                    "title": story.title,
                    "description": story.story_description,
                    "story_points": story.story_points,
                    "status": story.status.value if story.status else None,
                    "feature_title": feature_title,
                    "theme_title": theme_title,
                    "acceptance_criteria": story.acceptance_criteria,
                })

            print(f"   [DB] Found {len(stories)} backlog-ready stories.")

            return {
                "success": True,
                "product_id": query_input.product_id,
                "product_name": product.name,
                "total_stories": len(stories),
                "total_story_points": total_points,
                "stories_with_points": stories_with_points,
                "stories_without_points": len(stories) - stories_with_points,
                "stories": stories_data,
                "message": f"Found {len(stories)} backlog-ready stories ({total_points} total points).",
            }

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return {"success": False, "error": f"Database error: {str(e)}"}


# =============================================================================
# TOOL 2: PLAN SPRINT (Draft)
# =============================================================================


def plan_sprint_tool(
    plan_input: PlanSprintInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Draft a sprint plan for review.

    This tool:
    1. Validates selected stories are backlog-ready (TO_DO status)
    2. Calculates capacity utilization
    3. Proposes sprint dates
    4. Returns draft for user review (does NOT persist yet)

    The orchestrator should display this draft and let user modify
    before calling save_sprint_tool.
    """
    # Handle dict input from ADK
    if isinstance(plan_input, dict):
        plan_input = PlanSprintInput(**plan_input)

    print(f"\n[Tool: plan_sprint_tool] Drafting sprint for product {plan_input.product_id}...")

    try:
        with Session(engine) as session:
            # Verify product
            product = session.get(Product, plan_input.product_id)
            if not product:
                return {"success": False, "error": f"Product {plan_input.product_id} not found."}

            # Get or find team - track if we auto-created for disclosure
            team_id = plan_input.team_id
            team_auto_created = False
            
            if not team_id:
                # Try to find first team linked to product
                from agile_sqlmodel import ProductTeam

                team_link = session.exec(
                    select(ProductTeam).where(ProductTeam.product_id == plan_input.product_id)
                ).first()
                if team_link:
                    team_id = team_link.team_id
                else:
                    # Look for existing team by name or create default team
                    default_team_name = f"Team {product.name}"
                    existing_team = session.exec(
                        select(Team).where(Team.name == default_team_name)
                    ).first()
                    if existing_team:
                        team_id = existing_team.team_id
                        print(f"   [DB] Using existing team: {existing_team.name}")
                        # Link team to product if not already linked
                        existing_link = session.exec(
                            select(ProductTeam).where(
                                ProductTeam.product_id == plan_input.product_id,
                                ProductTeam.team_id == team_id
                            )
                        ).first()
                        if not existing_link:
                            product_team_link = ProductTeam(
                                product_id=plan_input.product_id,
                                team_id=team_id
                            )
                            session.add(product_team_link)
                            session.commit()
                            print(f"   [DB] Linked team to product")
                    else:
                        # AUTO-CREATE: First sprint for this product
                        default_team = Team(name=default_team_name)
                        session.add(default_team)
                        session.commit()
                        session.refresh(default_team)
                        team_id = default_team.team_id
                        team_auto_created = True
                        print(f"   [DB] Created default team: {default_team.name}")
                        # Link new team to product
                        product_team_link = ProductTeam(
                            product_id=plan_input.product_id,
                            team_id=team_id
                        )
                        session.add(product_team_link)
                        session.commit()
                        print(f"   [DB] Linked team to product")

            team = session.get(Team, team_id)
            if not team:
                return {"success": False, "error": f"Team {team_id} not found."}

            # Validate selected stories
            validated_stories: List[Dict[str, Any]] = []
            invalid_stories: List[Dict[str, Any]] = []
            total_points = 0

            for story_id in plan_input.selected_story_ids:
                story = session.get(UserStory, story_id)
                if not story:
                    invalid_stories.append({"story_id": story_id, "reason": "Not found"})
                    continue

                if story.product_id != plan_input.product_id:
                    invalid_stories.append({"story_id": story_id, "reason": "Wrong product"})
                    continue

                if story.status != StoryStatus.TO_DO:
                    invalid_stories.append({
                        "story_id": story_id,
                        "reason": f"Not backlog-ready (status: {story.status.value})",
                    })
                    continue

                # Story is valid
                validated_stories.append({
                    "story_id": story.story_id,
                    "title": story.title,
                    "story_points": story.story_points,
                    "feature_title": story.feature.title if story.feature else None,
                })
                total_points += story.story_points or 0

            # Calculate dates
            if plan_input.start_date:
                start = date.fromisoformat(plan_input.start_date)
            else:
                start = date.today()

            end = start + timedelta(days=plan_input.duration_days)

            # Calculate capacity utilization
            capacity_used_pct = None
            if plan_input.capacity_points and plan_input.capacity_points > 0:
                capacity_used_pct = round((total_points / plan_input.capacity_points) * 100, 1)

            # Emit draft event for metrics
            if tool_context:
                session_id = tool_context.state.get("session_id")
                _emit_workflow_event(
                    session,
                    WorkflowEventType.SPRINT_PLAN_DRAFT,
                    product_id=plan_input.product_id,
                    session_id=session_id,
                    event_metadata={
                        "story_count": len(validated_stories),
                        "total_points": total_points,
                        "capacity_points": plan_input.capacity_points,
                    },
                )

            # Store draft in context for later save
            draft: Dict[str, Any] = {
                "product_id": plan_input.product_id,
                "product_name": product.name,
                "team_id": team_id,
                "team_name": team.name,
                "team_auto_created": team_auto_created,
                "sprint_goal": plan_input.sprint_goal,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "duration_days": plan_input.duration_days,
                "validated_stories": validated_stories,
                "invalid_stories": invalid_stories,
                "total_story_points": total_points,
                "capacity_points": plan_input.capacity_points,
                "capacity_used_pct": capacity_used_pct,
                "task_breakdown": [t.model_dump() for t in plan_input.task_breakdown] if plan_input.task_breakdown else None,
            }

            # Store in tool context for save_sprint_tool
            if tool_context:
                tool_context.state["sprint_draft"] = draft
                tool_context.state["sprint_planning_start_time"] = _utc_now_iso()

            print(f"   [Draft] {len(validated_stories)} stories, {total_points} points")

            # Build message with explicit team disclosure
            team_notice = ""
            if team_auto_created:
                team_notice = f"ℹ️ Created '{team.name}' as your default team. You can rename it later.\n\n"
            
            return {
                "success": True,
                "is_draft": True,
                "draft": draft,
                "warnings": invalid_stories if invalid_stories else None,
                "message": (
                    f"{team_notice}"
                    f"**Sprint Draft for {team.name}**\n"
                    f"Goal: {plan_input.sprint_goal}\n"
                    f"Duration: {start.isoformat()} → {end.isoformat()} ({plan_input.duration_days} days)\n"
                    f"Stories: {len(validated_stories)} selected"
                    f"{f' ({total_points} points)' if total_points > 0 else ''}\n"
                    f"{'⚠️ ' + str(len(invalid_stories)) + ' stories excluded.' if invalid_stories else ''}"
                    f"\nReview and confirm to save."
                ),
            }

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return {"success": False, "error": f"Database error: {str(e)}"}


# =============================================================================
# TOOL 3: SAVE SPRINT (Idempotent Persistence)
# =============================================================================


def save_sprint_tool(
    save_input: SaveSprintInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Persist a sprint plan to the database (idempotent).

    This tool:
    1. Creates the Sprint record (or updates if exists with same goal/dates)
    2. Links stories via SprintStory (skips duplicates)
    3. Optionally creates Task records
    4. Emits workflow_events for metrics
    5. Triggers TLX prompt suggestion

    Idempotency: Re-calling with same data will not create duplicates.
    """
    # Handle dict input from ADK
    if isinstance(save_input, dict):
        save_input = SaveSprintInput(**save_input)

    print(f"\n[Tool: save_sprint_tool] Saving sprint for product {save_input.product_id}...")

    try:
        with Session(engine) as session:
            # Calculate planning duration
            planning_duration = None
            if save_input.planning_start_time:
                start_time = datetime.fromisoformat(
                    save_input.planning_start_time.replace("Z", "+00:00")
                )
                planning_duration = (_utc_now() - start_time).total_seconds()
            elif tool_context and "sprint_planning_start_time" in tool_context.state:
                start_time = datetime.fromisoformat(
                    tool_context.state["sprint_planning_start_time"].replace("Z", "+00:00")
                )
                planning_duration = (_utc_now() - start_time).total_seconds()

            # Parse dates
            start_date = date.fromisoformat(save_input.start_date)
            end_date = date.fromisoformat(save_input.end_date)

            # Check for existing sprint with same product/team/dates (idempotency)
            existing_sprint = session.exec(
                select(Sprint).where(
                    Sprint.product_id == save_input.product_id,
                    Sprint.team_id == save_input.team_id,
                    Sprint.start_date == start_date,
                    Sprint.end_date == end_date,
                )
            ).first()

            if existing_sprint:
                sprint = existing_sprint
                # Update goal if changed
                if sprint.goal != save_input.sprint_goal:
                    sprint.goal = save_input.sprint_goal
                    session.add(sprint)
                    session.commit()
                print(f"   [DB] Using existing sprint ID: {sprint.sprint_id}")
            else:
                # Create new sprint
                sprint = Sprint(
                    goal=save_input.sprint_goal,
                    start_date=start_date,
                    end_date=end_date,
                    status=SprintStatus.PLANNED,
                    product_id=save_input.product_id,
                    team_id=save_input.team_id,
                )
                session.add(sprint)
                session.commit()
                session.refresh(sprint)
                print(f"   [DB] Created sprint ID: {sprint.sprint_id}")

            # Link stories (idempotent - skip existing links)
            stories_linked = 0
            stories_skipped = 0
            total_points = 0

            assert sprint.sprint_id is not None, "Sprint must have an ID after save"

            # Optimization: Batch fetch existing links
            existing_links = session.exec(
                select(SprintStory.story_id).where(
                    SprintStory.sprint_id == sprint.sprint_id,
                    SprintStory.story_id.in_(save_input.selected_story_ids)
                )
            ).all()
            existing_story_ids = set(existing_links)

            # Identify stories that need processing
            stories_to_process_ids = []
            seen_ids_in_batch = set()
            for story_id in save_input.selected_story_ids:
                if story_id in existing_story_ids:
                    stories_skipped += 1
                elif story_id in seen_ids_in_batch:
                    # Duplicate in input: conceptually "skipped" as it will be linked by the first occurrence
                    stories_skipped += 1
                else:
                    stories_to_process_ids.append(story_id)
                    seen_ids_in_batch.add(story_id)

            if stories_to_process_ids:
                # Batch fetch stories
                stories_to_process = session.exec(
                    select(UserStory).where(
                        UserStory.story_id.in_(stories_to_process_ids)
                    )
                ).all()

                # Create a map for easy lookup
                stories_map = {s.story_id: s for s in stories_to_process}

                for story_id in stories_to_process_ids:
                    story = stories_map.get(story_id)

                    # Verify story exists and is ready
                    if not story or story.status != StoryStatus.TO_DO:
                        continue

                    # Create link
                    link = SprintStory(sprint_id=sprint.sprint_id, story_id=story_id)
                    session.add(link)
                    stories_linked += 1
                    total_points += story.story_points or 0

                    # Update story status to IN_PROGRESS
                    story.status = StoryStatus.IN_PROGRESS
                    session.add(story)

            session.commit()

            # Create tasks if provided
            tasks_created = 0
            if save_input.task_breakdown:
                for breakdown in save_input.task_breakdown:
                    for task_desc in breakdown.tasks:
                        # Check for existing task (idempotent)
                        existing_task = session.exec(
                            select(Task).where(
                                Task.story_id == breakdown.story_id,
                                Task.description == task_desc,
                            )
                        ).first()
                        if not existing_task:
                            task = Task(
                                story_id=breakdown.story_id,
                                description=task_desc,
                            )
                            session.add(task)
                            tasks_created += 1
                session.commit()

            # Emit workflow event for metrics
            session_id = None
            if tool_context:
                session_id = tool_context.state.get("session_id")

            event = _emit_workflow_event(
                session,
                WorkflowEventType.SPRINT_PLAN_SAVED,
                product_id=save_input.product_id,
                sprint_id=sprint.sprint_id,
                session_id=session_id,
                duration_seconds=planning_duration,
                turn_count=save_input.planning_turn_count,
                event_metadata={
                    "stories_linked": stories_linked,
                    "stories_skipped": stories_skipped,
                    "total_points": total_points,
                    "tasks_created": tasks_created,
                },
            )

            # Clear draft from context
            if tool_context and "sprint_draft" in tool_context.state:
                tool_context.state["sprint_draft"] = None  # Reset instead of delete

            print(f"   [DB] Linked {stories_linked} stories, created {tasks_created} tasks")

            # Get team name for response
            team = session.get(Team, save_input.team_id)
            team_name = team.name if team else f"Team #{save_input.team_id}"

            return {
                "success": True,
                "sprint_id": sprint.sprint_id,
                "sprint_goal": sprint.goal,
                "team_id": save_input.team_id,
                "team_name": team_name,
                "start_date": sprint.start_date.isoformat(),
                "end_date": sprint.end_date.isoformat(),
                "stories_linked": stories_linked,
                "stories_skipped": stories_skipped,
                "total_story_points": total_points,
                "tasks_created": tasks_created,
                "planning_duration_seconds": planning_duration,
                "event_id": event.event_id,
                "tlx_prompt": (
                    "🎯 Sprint planning complete! "
                    "Consider completing the NASA-TLX questionnaire to measure cognitive load."
                ),
                "message": (
                    f"✅ **Sprint #{sprint.sprint_id} saved for {team_name}**\n"
                    f"Goal: {sprint.goal}\n"
                    f"Duration: {sprint.start_date.isoformat()} → {sprint.end_date.isoformat()}\n"
                    f"Stories: {stories_linked} linked ({total_points} points)\n"
                    f"Tasks: {tasks_created} created"
                ),
            }

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        return {"success": False, "error": f"Database error: {str(e)}"}


# =============================================================================
# ADDITIONAL HELPER: CALCULATE SUGGESTED CAPACITY
# =============================================================================


def calculate_suggested_capacity(
    total_points: int,
    story_count: int,
    team_size: int = 1,
    sprint_days: int = 10,
) -> Dict[str, Any]:
    """
    Calculate suggested sprint capacity based on various heuristics.

    Heuristics:
    - If story points available: use points-based capacity
    - If no points: use story count (max 5-8 stories per sprint for small team)
    - Factor in team size and sprint length

    Returns suggestions for capacity planning.
    """
    suggestions: Dict[str, Any] = {}

    if total_points > 0:
        # Points-based suggestion
        # Rule of thumb: 8-12 points per person per week
        weekly_velocity = 10 * team_size
        sprint_weeks = sprint_days / 5
        suggested_capacity = int(weekly_velocity * sprint_weeks)
        suggestions["points_based"] = {
            "suggested_capacity": suggested_capacity,
            "reasoning": f"{weekly_velocity} points/week × {sprint_weeks:.1f} weeks",
        }

    # Story count-based suggestion (fallback)
    # Rule of thumb: 3-5 stories per person per sprint
    stories_per_person = 4
    suggested_stories = stories_per_person * team_size
    suggestions["story_count_based"] = {
        "suggested_max_stories": suggested_stories,
        "reasoning": f"{stories_per_person} stories/person × {team_size} team members",
    }

    return suggestions
