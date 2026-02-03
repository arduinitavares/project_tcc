"""Tests for refactoring single_story.py."""

import os
import json
import pytest
from unittest.mock import MagicMock
from orchestrator_agent.agent_tools.story_pipeline.single_story import (
    process_single_story,
)
from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput

@pytest.fixture
def mock_pipeline_components(monkeypatch):
    # Mock resolve_spec_version_id in single_story
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.single_story.resolve_spec_version_id",
        lambda story_input, *args: (story_input, None)
    )

    # Mock setup_authority_and_alignment in single_story
    def mock_setup(*args):
        return (
            {"domain": "general"}, # authority_context
            "spec text",           # technical_spec
            [],                    # forbidden_capabilities
            [],                    # invariants
            None                   # error_response
        )
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.single_story.setup_authority_and_alignment",
        mock_setup
    )

    # Mock build_initial_state in single_story
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.single_story.build_initial_state",
        lambda *args: {"some": "state"}
    )

    # Mock create_pipeline_runner in single_story
    mock_runner = MagicMock()
    # Ensure runner has an agent attribute for extract_agent_instructions
    mock_runner.agent = MagicMock()
    mock_runner.agent.name = "MockAgent"
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.single_story.create_pipeline_runner",
        lambda *args: (mock_runner, MagicMock())
    )

    # Mock InMemorySessionService in single_story
    mock_session_service = MagicMock()
    mock_session = MagicMock()
    mock_session.id = "session_id"
    async def async_create(*args, **kwargs): return mock_session
    mock_session_service.create_session = async_create

    # Patch the CLASS in single_story
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.single_story.InMemorySessionService",
        MagicMock(return_value=mock_session_service)
    )

    # Mock execute_pipeline in single_story
    async def mock_execute(*args):
        return {"refinement_result": json.dumps({"is_valid": True, "refined_story": {"title": "T"}})}
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.single_story.execute_pipeline",
        mock_execute
    )

    # Mock process_pipeline_result in single_story
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.single_story.process_pipeline_result",
        lambda *args: {"success": True, "story": {}}
    )


@pytest.mark.asyncio
async def test_debug_dump_not_created_by_default(mock_pipeline_components, monkeypatch):
    """Test that the debug dump file is NOT created by default."""
    monkeypatch.delenv("STORY_PIPELINE_DEBUG_DUMP", raising=False)
    debug_file = "logs/debug_story_pipeline_input.txt"
    if os.path.exists(debug_file):
        os.remove(debug_file)

    input_data = ProcessStoryInput(
        product_id=1,
        product_name="Prod",
        feature_id=1,
        feature_title="Feat",
        theme_id=1,
        epic_id=1,
        theme="Theme",
        epic="Epic",
        spec_version_id=1
    )

    await process_single_story(input_data)

    assert not os.path.exists(debug_file), "Debug file should not be created by default"


@pytest.mark.asyncio
async def test_debug_dump_created_when_enabled(mock_pipeline_components, monkeypatch):
    """Test that the debug dump file IS created when enabled via flag."""
    debug_file = "logs/debug_story_pipeline_input.txt"
    if os.path.exists(debug_file):
        os.remove(debug_file)

    input_data = ProcessStoryInput(
        product_id=1,
        product_name="Prod",
        feature_id=1,
        feature_title="Feat",
        theme_id=1,
        epic_id=1,
        theme="Theme",
        epic="Epic",
        spec_version_id=1
    )

    # Use Env Var
    monkeypatch.setenv("STORY_PIPELINE_DEBUG_DUMP", "1")

    await process_single_story(input_data)

    assert os.path.exists(debug_file), "Debug file should be created when enabled"
