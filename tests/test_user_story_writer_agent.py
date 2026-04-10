"""TDD tests for User Story Writer agent factory and configuration."""

from __future__ import annotations

from pathlib import Path

from orchestrator_agent.agent_tools.user_story_writer_tool.agent import (
    INSTRUCTIONS_PATH,
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
    assert root_agent.output_key == "story_output"


def test_factory_returns_new_instance() -> None:
    new_agent = create_user_story_writer_agent()
    assert new_agent is not root_agent
    assert new_agent.name == "user_story_writer_tool"


def test_instructions_example_does_not_include_placeholder_warning_on_high_story() -> (
    None
):
    instructions = Path(INSTRUCTIONS_PATH).read_text(encoding="utf-8")
    assert (
        '"decomposition_warning": "Only include this key if score is Low"'
        not in instructions
    )


def test_instructions_forbid_warning_on_non_low_scores() -> None:
    instructions = Path(INSTRUCTIONS_PATH).read_text(encoding="utf-8")
    assert (
        "Never include `decomposition_warning` on a story scored `High` or `Medium`."
        in instructions
    )
