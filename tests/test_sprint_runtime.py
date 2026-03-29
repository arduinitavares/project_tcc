"""Regression tests for sprint input normalization and runtime wiring."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from orchestrator_agent.fsm import deterministic_tool_adapters as adapters
from services import sprint_input, sprint_runtime
from utils import adk_runner


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
                    "tasks": [
                        {
                            "description": "Create schema",
                            "task_kind": "design",
                            "checklist_items": [
                                "Define the event schema shape",
                                "Document the persistence boundary",
                            ],
                            "artifact_targets": ["event schema"],
                            "workstream_tags": ["persistence"],
                            "relevant_invariant_ids": ["INV-12"],
                        },
                        {
                            "description": "Write tests",
                            "task_kind": "testing",
                            "checklist_items": [
                                "Cover the persistence behavior in tests",
                            ],
                            "artifact_targets": ["unit tests"],
                            "workstream_tags": ["testing"],
                            "relevant_invariant_ids": [],
                        },
                    ],
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
                    "evaluated_invariant_ids": [],
                },
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": ["INV-12"],
                    "source_requirement": "REQ-44",
                },
            ],
        }

    async def fake_invoke(payload):
        runtime_capture["payload"] = payload.model_dump()
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
                "story_description": "",
                "acceptance_criteria_items": [],
                "persona": None,
                "source_requirement": "REQ-44",
                "priority": 2,
                "story_points": 3,
                "evaluated_invariant_ids": ["INV-12"],
                "story_compliance_boundary_summaries": [],
            }
        ],
        "team_velocity_assumption": "High",
        "sprint_duration_days": 31,
        "user_context": "Focus on persistence",
        "max_story_points": 13,
        "include_task_decomposition": False,
    }


@pytest.mark.asyncio
async def test_runtime_rejects_out_of_scope_task_invariant_bindings(monkeypatch) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                }
            ],
        }

    async def fake_invoke(_payload):
        return _valid_sprint_output()

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=None,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is False
    assert result["error"] == "Sprint output validation failed: invalid task invariant bindings"


@pytest.mark.asyncio
async def test_runtime_passes_story_acceptance_criteria_into_decomposition_validator(monkeypatch) -> None:
    captured = {}

    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": ["INV-12"],
                    "acceptance_criteria": "Persist the event\nSurface a success response",
                }
            ],
        }

    async def fake_invoke(_payload):
        return _valid_sprint_output()

    def fake_validate_task_decomposition_quality(
        _output,
        *,
        include_task_decomposition,
        has_acceptance_criteria_by_story,
        acceptance_criteria_items_by_story=None,
    ):
        captured["include_task_decomposition"] = include_task_decomposition
        captured["has_acceptance_criteria_by_story"] = has_acceptance_criteria_by_story
        captured["acceptance_criteria_items_by_story"] = acceptance_criteria_items_by_story
        return []

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)
    monkeypatch.setattr(
        sprint_runtime,
        "validate_task_decomposition_quality",
        fake_validate_task_decomposition_quality,
    )

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=None,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is True
    assert captured["include_task_decomposition"] is True
    assert captured["has_acceptance_criteria_by_story"] == {12: True}
    assert captured["acceptance_criteria_items_by_story"] == {
        12: ["Persist the event", "Surface a success response"]
    }


@pytest.mark.asyncio
async def test_runtime_rejects_poor_task_decomposition_quality(monkeypatch) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                    "acceptance_criteria": "Persist the event\nSurface a success response",
                }
            ],
        }

    async def fake_invoke(_payload):
        return json.dumps(
            {
                "sprint_goal": "goal",
                "sprint_number": 1,
                "duration_days": 14,
                "selected_stories": [
                    {
                        "story_id": 12,
                        "story_title": "Event Delta Persistence",
                        "tasks": [
                        {
                            "description": "Do the work",
                            "task_kind": "implementation",
                            "checklist_items": ["Persist the event"],
                            "artifact_targets": ["event persistence service"],
                            "workstream_tags": ["backend"],
                            "relevant_invariant_ids": [],
                        }
                    ],
                    "reason_for_selection": "reason",
                }
                ],
                "deselected_stories": [],
                "capacity_analysis": {
                    "velocity_assumption": "High",
                    "capacity_band": "6-7 stories",
                    "selected_count": 1,
                    "story_points_used": 3,
                    "max_story_points": 13,
                    "commitment_note": "Valid note",
                    "reasoning": "Valid reasoning",
                },
            }
        )

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=None,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is False
    assert result["error"] == "Sprint output validation failed: poor task decomposition quality"


@pytest.mark.asyncio
async def test_runtime_exposes_compact_public_task_kind_retry_hints(monkeypatch) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                }
            ],
        }

    async def fake_invoke(_payload):
        return json.dumps(
            {
                "sprint_goal": "goal",
                "sprint_number": 1,
                "duration_days": 14,
                "selected_stories": [
                    {
                        "story_id": 12,
                        "story_title": "Event Delta Persistence",
                        "tasks": [
                            {
                                "description": "Get approval",
                                "task_kind": "approval",
                                "checklist_items": ["Confirm the change can proceed"],
                                "artifact_targets": ["approval decision"],
                                "workstream_tags": ["governance"],
                                "relevant_invariant_ids": [],
                            }
                        ],
                        "reason_for_selection": "reason",
                    }
                ],
                "deselected_stories": [],
                "capacity_analysis": {
                    "velocity_assumption": "Medium",
                    "capacity_band": "4-5 stories",
                    "selected_count": 1,
                    "story_points_used": 3,
                    "max_story_points": 13,
                    "commitment_note": "Does this scope feel achievable in 2 weeks?",
                    "reasoning": "Fits the chosen capacity.",
                },
            }
        )

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=13,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is False
    assert result["failure_stage"] == "output_validation"
    assert result["output_artifact"]["validation_errors"] == [
        "Task 'Get approval' uses unsupported task_kind 'approval'. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]


@pytest.mark.asyncio
async def test_runtime_uses_canonical_public_hint_for_non_string_task_kind(
    monkeypatch,
) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                }
            ],
        }

    async def fake_invoke(_payload):
        return json.dumps(
            {
                "sprint_goal": "goal",
                "sprint_number": 1,
                "duration_days": 14,
                "selected_stories": [
                    {
                        "story_id": 12,
                        "story_title": "Event Delta Persistence",
                        "tasks": [
                            {
                                "description": "Get approval",
                                "task_kind": None,
                                "checklist_items": ["Confirm the change can proceed"],
                                "artifact_targets": ["approval decision"],
                                "workstream_tags": ["governance"],
                                "relevant_invariant_ids": [],
                            }
                        ],
                        "reason_for_selection": "reason",
                    }
                ],
                "deselected_stories": [],
                "capacity_analysis": {
                    "velocity_assumption": "Medium",
                    "capacity_band": "4-5 stories",
                    "selected_count": 1,
                    "story_points_used": 3,
                    "max_story_points": 13,
                    "commitment_note": "Does this scope feel achievable in 2 weeks?",
                    "reasoning": "Fits the chosen capacity.",
                },
            }
        )

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=13,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is False
    assert result["failure_stage"] == "output_validation"
    assert result["output_artifact"]["validation_errors"] == [
        "Task 'Get approval' has invalid task_kind. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]
    assert "other" not in result["output_artifact"]["validation_errors"][0]


@pytest.mark.asyncio
async def test_adk_runner_preserves_structured_validation_details(monkeypatch) -> None:
    structured_errors = [
        {
            "type": "literal_error",
            "loc": ("selected_stories", 0, "tasks", 0, "task_kind"),
            "msg": "Input should be 'analysis' or 'design'",
            "input": "approval",
        }
    ]

    class FakeSessionService:
        async def create_session(self, *, app_name, user_id):
            return SimpleNamespace(id="session-1")

    class FakeRunner:
        def __init__(self, *, agent, app_name, session_service):
            self.agent = agent
            self.app_name = app_name
            self.session_service = session_service

        async def run_async(self, *, user_id, session_id, new_message):
            _ = (user_id, session_id, new_message)
            class FakeStructuredValidationError(Exception):
                def errors(self):
                    return structured_errors

            raise RuntimeError("ADK validation failed") from FakeStructuredValidationError()
            yield None

    class FakePart:
        @staticmethod
        def from_text(*, text):
            return SimpleNamespace(text=text)

    class FakeContent:
        def __init__(self, *, role, parts):
            self.role = role
            self.parts = parts

    monkeypatch.setattr(adk_runner, "InMemorySessionService", FakeSessionService)
    monkeypatch.setattr(adk_runner, "Runner", FakeRunner)
    monkeypatch.setattr(
        adk_runner,
        "types",
        SimpleNamespace(Content=FakeContent, Part=FakePart),
    )

    with pytest.raises(adk_runner.AgentInvocationError) as exc_info:
        await adk_runner.invoke_agent_to_text(
            agent=SimpleNamespace(name="sprint"),
            runner_identity=SimpleNamespace(app_name="app", user_id="user"),
            payload_json="{}",
            no_text_error="missing",
        )

    assert exc_info.value.validation_errors == structured_errors


@pytest.mark.asyncio
async def test_runtime_falls_back_to_public_hint_for_adk_task_kind_errors_without_input(
    monkeypatch,
) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                }
            ],
        }

    async def fake_invoke(_payload):
        raise adk_runner.AgentInvocationError(
            "ADK validation failed",
            validation_errors=[
                {
                    "type": "missing",
                    "loc": ("selected_stories", 0, "tasks", 0, "task_kind"),
                    "msg": "Field required",
                }
            ],
        )

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=13,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is False
    assert result["failure_stage"] == "invocation_exception"
    assert result["output_artifact"]["validation_errors"] == [
        "Task has invalid task_kind. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]
