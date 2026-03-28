"""Tests for sprint planner persistence tool."""

import json
from datetime import date
from datetime import datetime, timezone
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
    WorkflowEvent,
    WorkflowEventType,
)
from orchestrator_agent.agent_tools.sprint_planner_tool.tools import (
    SaveSprintPlanInput,
    save_sprint_plan_tool,
)
from utils.schemes import ValidationEvidence
from utils.task_metadata import TaskMetadata


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
            validation_evidence=ValidationEvidence(
                spec_version_id=1,
                validated_at=datetime.now(timezone.utc),
                passed=True,
                rules_checked=["SPEC_VERSION_EXISTS"],
                invariants_checked=[],
                evaluated_invariant_ids=["INV-VALID"] if idx == 0 else [],
                finding_invariant_ids=[],
                failures=[],
                warnings=[],
                alignment_warnings=[],
                alignment_failures=[],
                validator_version="1.0.0",
                input_hash="hash",
            ).model_dump_json(),
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
                "tasks": [
                    {
                        "description": "Create auth table",
                        "task_kind": "implementation",
                        "checklist_items": [
                            "Define the auth table columns",
                            "Add persistence coverage for auth records",
                        ],
                        "artifact_targets": ["auth schema"],
                        "workstream_tags": ["backend", "auth"],
                        "relevant_invariant_ids": ["INV-VALID"],
                    },
                    {
                        "description": "Add login UI",
                        "task_kind": "implementation",
                        "checklist_items": [
                            "Render the login form locally",
                            "Wire submit handling to the login flow",
                        ],
                        "artifact_targets": ["login form"],
                        "workstream_tags": ["frontend", "auth"],
                        "relevant_invariant_ids": [],
                    },
                ],
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
    assert sprint.started_at is None

    links = session.exec(select(SprintStory)).all()
    assert len(links) == 1

    tasks = session.exec(select(Task)).all()
    assert len(tasks) == 2
    metadata_by_description = {
        task.description: TaskMetadata.model_validate(json.loads(task.metadata_json))
        for task in tasks
    }
    assert metadata_by_description["Create auth table"].task_kind == "implementation"
    assert metadata_by_description["Create auth table"].artifact_targets == ["auth schema"]
    assert metadata_by_description["Create auth table"].checklist_items == [
        "Define the auth table columns",
        "Add persistence coverage for auth records",
    ]


def test_save_sprint_plan_uses_orchestrator_duration_when_valid(session: Session):
    """Persisted workflow event must keep a valid orchestrator-provided duration."""
    product_id, team_id, story_ids = _seed_product_team_stories(session)

    tool_context = cast(
        ToolContext,
        SimpleNamespace(
            state={
                "sprint_plan": _build_sprint_plan(story_ids),
                "sprint_planning_duration": 12.75,
            }
        ),
    )
    input_data = SaveSprintPlanInput(
        product_id=product_id,
        team_id=team_id,
        sprint_start_date="2026-02-01",
        sprint_duration_days=14,
    )

    result = save_sprint_plan_tool(input_data, tool_context)
    assert result["success"] is True

    event = session.exec(
        select(WorkflowEvent).where(
            WorkflowEvent.event_type == WorkflowEventType.SPRINT_PLAN_SAVED
        )
    ).first()
    assert event is not None
    assert event.duration_seconds == 12.75


def test_save_sprint_plan_falls_back_to_elapsed_duration(session: Session):
    """Persisted workflow event must include numeric duration when state key is missing."""
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

    event = session.exec(
        select(WorkflowEvent).where(
            WorkflowEvent.event_type == WorkflowEventType.SPRINT_PLAN_SAVED
        )
    ).first()
    assert event is not None
    assert event.duration_seconds is not None
    assert isinstance(event.duration_seconds, float)
    assert event.duration_seconds >= 0.0


def test_save_sprint_plan_falls_back_when_state_duration_invalid(session: Session):
    """Invalid state duration must not propagate as NULL to workflow event."""
    product_id, team_id, story_ids = _seed_product_team_stories(session)

    tool_context = cast(
        ToolContext,
        SimpleNamespace(
            state={
                "sprint_plan": _build_sprint_plan(story_ids),
                "sprint_planning_duration": "not-a-number",
            }
        ),
    )
    input_data = SaveSprintPlanInput(
        product_id=product_id,
        team_id=team_id,
        sprint_start_date="2026-02-01",
        sprint_duration_days=14,
    )

    result = save_sprint_plan_tool(input_data, tool_context)
    assert result["success"] is True

    event = session.exec(
        select(WorkflowEvent).where(
            WorkflowEvent.event_type == WorkflowEventType.SPRINT_PLAN_SAVED
        )
    ).first()
    assert event is not None
    assert event.duration_seconds is not None
    assert isinstance(event.duration_seconds, float)
    assert event.duration_seconds >= 0.0


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


def test_save_sprint_plan_rejects_out_of_scope_task_invariants(session: Session):
    product_id, team_id, story_ids = _seed_product_team_stories(session)
    sprint_plan = _build_sprint_plan(story_ids)
    sprint_plan["selected_stories"][0]["tasks"][0]["relevant_invariant_ids"] = ["INV-UNKNOWN"]

    tool_context = cast(
        ToolContext,
        SimpleNamespace(state={"sprint_plan": sprint_plan}),
    )
    input_data = SaveSprintPlanInput(
        product_id=product_id,
        team_id=team_id,
        sprint_start_date="2026-02-01",
        sprint_duration_days=14,
    )

    result = save_sprint_plan_tool(input_data, tool_context)

    assert result["success"] is False
    assert "invalid invariant IDs" in result["error"]


def test_save_sprint_plan_rejects_checklist_items_copied_from_story_acceptance_criteria(
    session: Session,
):
    product = Product(name="Checklist Product", vision="Vision", description="Desc")
    team = Team(name="Checklist Team")
    session.add(product)
    session.add(team)
    session.commit()
    session.refresh(product)
    session.refresh(team)

    assert product.product_id is not None
    assert team.team_id is not None

    story = UserStory(
        product_id=product.product_id,
        title="Story with AC",
        story_description="As a user, I want...",
        acceptance_criteria="1. Persist the event\n2. Surface a success response",
        validation_evidence=ValidationEvidence(
            spec_version_id=1,
            validated_at=datetime.now(timezone.utc),
            passed=True,
            rules_checked=["SPEC_VERSION_EXISTS"],
            invariants_checked=[],
            evaluated_invariant_ids=["INV-VALID"],
            finding_invariant_ids=[],
            failures=[],
            warnings=[],
            alignment_warnings=[],
            alignment_failures=[],
            validator_version="1.0.0",
            input_hash="hash",
        ).model_dump_json(),
    )
    session.add(story)
    session.commit()
    session.refresh(story)

    assert story.story_id is not None

    sprint_plan = {
        "sprint_goal": "Deliver authentication essentials",
        "sprint_number": 1,
        "duration_days": 14,
        "selected_stories": [
            {
                "story_id": story.story_id,
                "story_title": "Story with AC",
                "tasks": [
                    {
                        "description": "Create auth table",
                        "task_kind": "implementation",
                        "checklist_items": [
                            "Persist the event",
                            "Add persistence coverage for auth records",
                        ],
                        "artifact_targets": ["auth schema"],
                        "workstream_tags": ["backend", "auth"],
                        "relevant_invariant_ids": ["INV-VALID"],
                    }
                ],
                "reason_for_selection": "Core to sprint goal",
            }
        ],
        "deselected_stories": [],
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

    tool_context = cast(
        ToolContext,
        SimpleNamespace(state={"sprint_plan": sprint_plan}),
    )
    input_data = SaveSprintPlanInput(
        product_id=product.product_id,
        team_id=team.team_id,
        sprint_start_date="2026-02-01",
        sprint_duration_days=14,
    )

    result = save_sprint_plan_tool(input_data, tool_context)

    assert result["success"] is False
    assert "duplicates story acceptance criteria" in result["error"]
