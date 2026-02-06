"""Tests for sprint planner schemas."""

from typing import Any, Dict

from pydantic import ValidationError

from orchestrator_agent.agent_tools.sprint_planner_tool.schemes import (
    SprintPlannerCapacityAnalysis,
    SprintPlannerInput,
    SprintPlannerOutput,
    SprintPlannerSelectedStory,
)


def _build_output_payload() -> Dict[str, Any]:
    return {
        "sprint_goal": "Ship login onboarding",
        "sprint_number": 1,
        "duration_days": 14,
        "selected_stories": [
            {
                "story_id": 101,
                "story_title": "Enable login",
                "tasks": ["Create auth table", "Add login UI"],
                "reason_for_selection": "Core to sprint goal",
            }
        ],
        "deselected_stories": [
            {"story_id": 102, "reason": "Does not fit capacity"}
        ],
        "capacity_analysis": {
            "velocity_assumption": "Medium",
            "capacity_band": "4-5 stories",
            "selected_count": 1,
            "story_points_used": 3,
            "max_story_points": 10,
            "commitment_note": "Does this scope feel achievable in 2 weeks?",
            "reasoning": "Scope fits the band and aligns to the goal.",
        },
    }


def test_output_schema_round_trip():
    """Ensure output schema supports JSON round-trip validation."""
    payload = _build_output_payload()
    model = SprintPlannerOutput.model_validate(payload)
    dumped = model.model_dump_json()
    restored = SprintPlannerOutput.model_validate_json(dumped)
    assert restored.sprint_goal == payload["sprint_goal"]


def test_output_schema_rejects_extra_fields():
    """Ensure extra keys are rejected in output schema."""
    payload = _build_output_payload()
    payload["extra"] = "not allowed"
    try:
        SprintPlannerOutput.model_validate(payload)
    except ValidationError as exc:
        assert "extra" in str(exc)
    else:
        raise AssertionError("Expected ValidationError for extra fields")


def test_input_schema_accepts_optional_fields():
    """Ensure input schema accepts optional capacity and task flags."""
    input_payload: Dict[str, Any] = {
        "available_stories": [
            {
                "story_id": 101,
                "story_title": "Enable login",
                "priority": 1,
                "story_points": 3,
            }
        ],
        "team_velocity_assumption": "Low",
        "sprint_duration_days": 10,
        "user_context": "Focus on onboarding",
        "max_story_points": 8,
        "include_task_decomposition": False,
    }
    model = SprintPlannerInput.model_validate(input_payload)
    assert model.max_story_points == 8
    assert model.include_task_decomposition is False


def test_input_schema_requires_duration_days():
    """Ensure sprint duration is required in input schema."""
    input_payload: Dict[str, Any] = {
        "available_stories": [
            {
                "story_id": 101,
                "story_title": "Enable login",
                "priority": 1,
                "story_points": 3,
            }
        ],
        "team_velocity_assumption": "Low",
        "user_context": "Focus on onboarding",
        "max_story_points": 8,
        "include_task_decomposition": False,
    }
    try:
        SprintPlannerInput.model_validate(input_payload)
    except ValidationError as exc:
        assert "sprint_duration_days" in str(exc)
    else:
        raise AssertionError("Expected ValidationError for missing sprint_duration_days")


def test_selected_story_requires_reason():
    """Ensure selected stories include a reason for selection."""
    payload: Dict[str, Any] = {
        "story_id": 201,
        "story_title": "Password reset",
        "tasks": ["Add reset API"],
        "reason_for_selection": "Critical to account access",
    }
    model = SprintPlannerSelectedStory.model_validate(payload)
    assert model.story_id == 201


def test_capacity_analysis_requires_commitment_note():
    """Ensure capacity analysis includes commitment note."""
    payload: Dict[str, Any] = {
        "velocity_assumption": "High",
        "capacity_band": "6-7 stories",
        "selected_count": 6,
        "story_points_used": 12,
        "max_story_points": 15,
        "commitment_note": "Does this scope feel achievable in 2 weeks?",
        "reasoning": "Capacity fits the high band.",
    }
    model = SprintPlannerCapacityAnalysis.model_validate(payload)
    assert model.selected_count == 6
