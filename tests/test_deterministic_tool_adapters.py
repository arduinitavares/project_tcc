"""Tests for deterministic context-injection adapters."""

from __future__ import annotations

import inspect
import json

import pytest

from orchestrator_agent.fsm import deterministic_tool_adapters as adapters
from orchestrator_agent.fsm.definitions import STATE_REGISTRY
from orchestrator_agent.fsm.states import OrchestratorState


class MockToolContext:
    """Minimal ToolContext stub for unit tests."""

    def __init__(self, state):
        self.state = state


@pytest.mark.asyncio
async def test_product_vision_adapter_injects_state_verbatim(monkeypatch) -> None:
    captured = {}

    async def fake_run_async(*, args, tool_context):
        captured["args"] = args
        captured["tool_context"] = tool_context
        return {
            "updated_components": {},
            "product_vision_statement": "draft",
            "is_complete": False,
            "clarifying_questions": [],
        }

    monkeypatch.setattr(adapters._PRODUCT_VISION_TOOL, "run_async", fake_run_async)

    state = {
        "pending_spec_content": "SPEC_RAW",
        "compiled_authority_cached": "{\"invariants\":[\"x\"]}",
        "vision_components": {"project_name": "Demo"},
    }
    context = MockToolContext(state)

    result = await adapters.product_vision_tool(
        user_raw_text="refine the vision",
        tool_context=context,
    )

    assert result["is_complete"] is False
    assert captured["tool_context"] is context
    assert captured["args"]["user_raw_text"] == "refine the vision"
    assert captured["args"]["specification_content"] == "SPEC_RAW"
    assert captured["args"]["compiled_authority"] == "{\"invariants\":[\"x\"]}"
    assert captured["args"]["prior_vision_state"] == json.dumps(
        {"project_name": "Demo"},
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_backlog_adapter_fail_fast_on_missing_required_context(monkeypatch) -> None:
    async def fail_if_called(*, args, tool_context):
        pytest.fail("Sub-agent should not run when context is missing")

    monkeypatch.setattr(adapters._BACKLOG_PRIMER_TOOL, "run_async", fail_if_called)

    context = MockToolContext(
        {
            "active_project": {"vision": ""},
            "pending_spec_content": "",
            "compiled_authority_cached": "",
        }
    )

    result = await adapters.backlog_primer_tool(
        user_input="generate backlog",
        tool_context=context,
    )

    assert result["is_complete"] is False
    assert result["error"] == "BACKLOG_CONTEXT_MISSING"
    assert "active_project.vision" in result["missing_context"]
    assert "pending_spec_content" in result["missing_context"]
    assert "compiled_authority_cached" in result["missing_context"]


@pytest.mark.asyncio
async def test_roadmap_adapter_passes_full_payload_without_summarization(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_run_async(*, args, tool_context):
        captured["args"] = args
        return {
            "roadmap_releases": [],
            "roadmap_summary": "ok",
            "is_complete": False,
            "clarifying_questions": [],
        }

    monkeypatch.setattr(adapters._ROADMAP_BUILDER_TOOL, "run_async", fake_run_async)

    long_spec = "# Spec\n" + ("A" * 9000)
    long_authority = "{\"scope_themes\":[\"x\"],\"invariants\":[\"" + ("B" * 3500) + "\"]}"
    backlog_items = [
        {
            "priority": 1,
            "requirement": "Data Usage Eligibility Gate",
            "value_driver": "Strategic",
            "justification": "Mandatory legal gate",
            "estimated_effort": "M",
        }
    ]
    context = MockToolContext(
        {
            "active_project": {"vision": "Vision text"},
            "approved_backlog": {"items": backlog_items},
            "pending_spec_content": long_spec,
            "compiled_authority_cached": long_authority,
        }
    )

    _ = await adapters.roadmap_builder_tool(
        user_input="create roadmap",
        tool_context=context,
    )

    assert captured["args"]["product_vision"] == "Vision text"
    assert captured["args"]["backlog_items"] == backlog_items
    assert captured["args"]["technical_spec"] == long_spec
    assert captured["args"]["compiled_authority"] == long_authority
    assert len(captured["args"]["technical_spec"]) == len(long_spec)
    assert len(captured["args"]["compiled_authority"]) == len(long_authority)


@pytest.mark.asyncio
async def test_story_adapter_derives_requirement_context_from_roadmap(
    monkeypatch,
) -> None:
    captured = {}

    async def fake_run_async(*, args, tool_context):
        captured["args"] = args
        return {
            "parent_requirement": args["parent_requirement"],
            "user_stories": [
                {
                    "story_title": "Title",
                    "statement": "As a reviewer, I want X, so that Y.",
                    "acceptance_criteria": ["Verify that X."],
                    "invest_score": "High",
                }
            ],
            "is_complete": True,
            "clarifying_questions": [],
        }

    monkeypatch.setattr(adapters._USER_STORY_WRITER_TOOL, "run_async", fake_run_async)

    roadmap = {
        "roadmap_releases": [
            {
                "release_name": "Milestone 1",
                "theme": "Legal Safety",
                "focus_area": "Technical Foundation",
                "items": ["Data Usage Eligibility Gate (mandatory pre-persist)"],
                "reasoning": "Gate must block persistence before attestations.",
            }
        ]
    }
    context = MockToolContext(
        {
            "active_project": {"roadmap": roadmap},
            "pending_spec_content": "SPEC_TEXT",
            "compiled_authority_cached": "{\"invariants\":[]}",
        }
    )

    await adapters.user_story_writer_tool(
        parent_requirement="Data Usage Eligibility Gate (mandatory pre-persist)",
        requirement_context="MANUAL_CONTEXT_SHOULD_NOT_OVERRIDE_DERIVED",
        tool_context=context,
    )

    derived = captured["args"]["requirement_context"]
    assert "Theme: Legal Safety" in derived
    assert "Focus Area: Technical Foundation" in derived
    assert "Reasoning: Gate must block persistence before attestations." in derived


@pytest.mark.asyncio
async def test_story_adapter_fail_fast_without_derived_or_explicit_context(
    monkeypatch,
) -> None:
    async def fail_if_called(*, args, tool_context):
        pytest.fail("Sub-agent should not run when requirement context is unavailable")

    monkeypatch.setattr(adapters._USER_STORY_WRITER_TOOL, "run_async", fail_if_called)

    context = MockToolContext(
        {
            "pending_spec_content": "SPEC_TEXT",
            "compiled_authority_cached": "{\"invariants\":[]}",
            # No roadmap in active_project and no roadmap_result
        }
    )

    result = await adapters.user_story_writer_tool(
        parent_requirement="Data Usage Eligibility Gate (mandatory pre-persist)",
        requirement_context="",
        tool_context=context,
    )

    assert result["is_complete"] is False
    assert result["error"] == "STORY_CONTEXT_MISSING"
    assert (
        "roadmap release metadata (or explicit requirement_context)"
        in result["missing_context"]
    )


def test_state_registry_keeps_public_generation_tool_names() -> None:
    routing_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
    tool_names = [
        getattr(tool, "__name__", None) or getattr(tool, "name", None)
        for tool in routing_def.tools
    ]

    assert "product_vision_tool" in tool_names
    assert "backlog_primer_tool" in tool_names
    assert "roadmap_builder_tool" in tool_names
    assert "user_story_writer_tool" in tool_names
    assert len(tool_names) == len(set(tool_names))


def test_minimal_adapter_signatures_remove_legacy_context_fields() -> None:
    vision_params = inspect.signature(adapters.product_vision_tool).parameters
    backlog_params = inspect.signature(adapters.backlog_primer_tool).parameters
    roadmap_params = inspect.signature(adapters.roadmap_builder_tool).parameters
    story_params = inspect.signature(adapters.user_story_writer_tool).parameters

    assert "specification_content" not in vision_params
    assert "compiled_authority" not in vision_params
    assert "prior_vision_state" not in vision_params

    assert "product_vision_statement" not in backlog_params
    assert "technical_spec" not in backlog_params
    assert "compiled_authority" not in backlog_params
    assert "prior_backlog_state" not in backlog_params

    assert "backlog_items" not in roadmap_params
    assert "product_vision" not in roadmap_params
    assert "technical_spec" not in roadmap_params
    assert "compiled_authority" not in roadmap_params
    assert "prior_roadmap_state" not in roadmap_params

    assert "technical_spec" not in story_params
    assert "compiled_authority" not in story_params
