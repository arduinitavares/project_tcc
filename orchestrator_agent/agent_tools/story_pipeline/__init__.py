# orchestrator_agent/agent_tools/story_pipeline/__init__.py
"""
Story Pipeline - LoopAgent + SequentialAgent hybrid architecture.

Processes ONE story at a time through:
1. StoryDraftAgent - Generates initial story from feature
2. SpecValidatorAgent - Validates spec compliance
3. StoryRefinerAgent - Refines based on validation feedback

Loops until valid or max_iterations reached.
"""

from orchestrator_agent.agent_tools.story_pipeline.pipeline import (
    story_validation_loop,
)
from orchestrator_agent.agent_tools.story_pipeline.tools import (
    process_single_story,
)

__all__ = [
    "story_validation_loop",
    "process_single_story",
]
