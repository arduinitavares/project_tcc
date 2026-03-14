"""Regression tests for sprint input normalization and runtime wiring."""

from __future__ import annotations

import json

import pytest

from orchestrator_agent.fsm import deterministic_tool_adapters as adapters
from services import sprint_input, sprint_runtime


class MockToolContext:
    """Minimal ToolContext stub for unit tests."""

    def __init__(self, state):
        self.state = state


def _valid_sprint_output() -> str:
    return json.dumps(
        {
            "sprint_goal": "Deliver onboarding-ready login flow",
            "sprint_number": 1,
            "duration_days": 14,
            "selected_stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "tasks": ["Create schema", "Write tests"],
                    "reason_for_selection": "Supports the sprint goal.",
                }
            ],
            "deselected_stories": [
                {
                    "story_id": 11,
                    "reason": "Fits a later sprint better.",
                }
            ],
            "capacity_analysis": {
                "velocity_assumption": "High",
                "capacity_band": "6-7 stories",
                "selected_count": 1,
                "story_points_used": 3,
                "max_story_points": 13,
                "commitment_note": "Does this scope feel achievable in 2 weeks?",
                "reasoning": "This scope fits the chosen capacity band.",
            },
        }
    )


def test_prepare_sprint_input_context_rejects_invalid_selected_story_ids(monkeypatch) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 11,
                    "story_title": "Attestation Gate UI",
                    "priority": 1,
                    "story_points": 5,
                }
            ],
        }

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)

    prepared = sprint_input.prepare_sprint_input_context(
        product_id=7,
        team_velocity_assumption="High",
        sprint_duration_days=14,
        user_context="Focus on persistence",
        max_story_points=13,
        include_task_decomposition=True,
        selected_story_ids=[999],
    )

    assert prepared["success"] is False
    assert prepared["error_code"] == "SPRINT_SELECTION_INVALID"
    assert prepared["invalid_selected_ids"] == [999]


@pytest.mark.asyncio
async def test_runtime_and_adapter_build_matching_sprint_input(monkeypatch) -> None:
    runtime_capture = {}
    adapter_capture = {}

    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 2,
            "stories": [
                {
                    "story_id": 11,
                    "story_title": "Attestation Gate UI",
                    "priority": 1,
                    "story_points": 5,
                },
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                },
            ],
        }

    async def fake_invoke(payload):
        runtime_capture["payload"] = payload.model_dump(exclude_none=True)
        return _valid_sprint_output()

    async def fake_run_async(*, args, tool_context):
        adapter_capture["args"] = args
        adapter_capture["tool_context"] = tool_context
        return {"sprint_goal": "goal", "selected_stories": [], "capacity_analysis": {}}

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(adapters, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)
    monkeypatch.setattr(adapters._SPRINT_PLANNER_TOOL, "run_async", fake_run_async)

    runtime_result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="high",
        sprint_duration_days=40,
        max_story_points=13,
        include_task_decomposition=False,
        selected_story_ids=[12],
        user_input="Focus on persistence",
    )
    context = MockToolContext({"active_project": {"product_id": 7}})
    _ = await adapters.sprint_planner_tool(
        team_velocity_assumption="high",
        sprint_duration_days=40,
        user_context="Focus on persistence",
        max_story_points=13,
        include_task_decomposition=False,
        selected_story_ids=[12],
        tool_context=context,
    )

    assert runtime_result["success"] is True
    assert runtime_result["output_artifact"]["is_complete"] is True
    assert runtime_capture["payload"] == adapter_capture["args"]
    assert runtime_capture["payload"] == {
        "available_stories": [
            {
                "story_id": 12,
                "story_title": "Event Delta Persistence",
                "priority": 2,
                "story_points": 3,
            }
        ],
        "team_velocity_assumption": "High",
        "sprint_duration_days": 31,
        "user_context": "Focus on persistence",
        "max_story_points": 13,
        "include_task_decomposition": False,
    }
