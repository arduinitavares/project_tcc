"""TDD tests for User Story Writer agent factory and configuration."""

from __future__ import annotations

from orchestrator_agent.agent_tools.user_story_writer_tool.agent import (
    create_user_story_writer_agent,
    root_agent,
)
from orchestrator_agent.agent_tools.user_story_writer_tool.schemes import (
    UserStoryWriterInput,
    UserStoryWriterOutput,
)


def test_agent_has_correct_name() -> None:
    assert root_agent.name == "user_story_writer_tool"


def test_agent_has_input_schema() -> None:
    assert root_agent.input_schema is UserStoryWriterInput


def test_agent_has_output_schema() -> None:
    assert root_agent.output_schema is UserStoryWriterOutput


def test_agent_has_output_key() -> None:
    assert root_agent.output_key == "story_writer_result"


def test_factory_returns_new_instance() -> None:
    new_agent = create_user_story_writer_agent()
    assert new_agent is not root_agent
    assert new_agent.name == "user_story_writer_tool"
