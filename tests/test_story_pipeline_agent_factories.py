from __future__ import annotations

from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import (
    create_story_draft_agent,
    story_draft_agent,
)
from orchestrator_agent.agent_tools.story_pipeline.story_refiner_agent.agent import (
    create_story_refiner_agent,
    story_refiner_agent,
)


def test_create_story_draft_agent_returns_new_instance() -> None:
    new_agent = create_story_draft_agent()
    assert new_agent is not story_draft_agent


def test_create_story_refiner_agent_returns_new_instance() -> None:
    new_agent = create_story_refiner_agent()
    assert new_agent is not story_refiner_agent
