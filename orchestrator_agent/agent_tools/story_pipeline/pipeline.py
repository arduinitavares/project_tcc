# orchestrator_agent/agent_tools/story_pipeline/pipeline.py
"""
Story Validation Pipeline - LoopAgent + SequentialAgent hybrid.

Architecture:
┌──────────────────────────────────────────────────────────────┐
│                 LoopAgent (max_iterations=2)                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │            SequentialAgent (per story)                  │ │
│  │                                                         │ │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │ │
│  │  │ StoryDraft  │ → │  INVEST     │ → │ StoryRefine │   │ │
│  │  │   Agent     │   │  Validator  │   │   Agent     │   │ │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   │ │
│  │        ↓                 ↓                 ↓            │ │
│  │   state['draft']   state['valid']   state['refined']   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                              ↓                               │
│         Iteration 1: Draft story, validate, get feedback     │
│         Iteration 2: Refine based on feedback, validate      │
└──────────────────────────────────────────────────────────────┘

The pipeline processes ONE feature → ONE story at a time.
Two iterations provide:
1. Initial draft + validation feedback
2. Refined story incorporating feedback (typically improves 5-10 points)
"""

from google.adk.agents import SequentialAgent, LoopAgent

from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import (
    story_draft_agent,
)
from orchestrator_agent.agent_tools.story_pipeline.invest_validator_agent.agent import (
    invest_validator_agent,
)
from orchestrator_agent.agent_tools.story_pipeline.story_refiner_agent.agent import (
    story_refiner_agent,
)


# --- Sequential Pipeline ---
# Runs: Draft → Validate → Refine in strict order
story_sequential_pipeline = SequentialAgent(
    name="StorySequentialPipeline",
    sub_agents=[story_draft_agent, invest_validator_agent, story_refiner_agent],
    description="Drafts a story, validates it, and refines if needed.",
)


# --- Loop Agent ---
# Wraps the sequential pipeline to retry if validation fails
# Exits EARLY when refiner calls exit_loop (score >= 90)
# max_iterations is a safety limit, not the typical case
story_validation_loop = LoopAgent(
    name="StoryValidationLoop",
    sub_agents=[story_sequential_pipeline],
    max_iterations=3,  # Safety limit - usually exits early via exit_loop tool
    description="Loops through story creation until INVEST-valid (exits early when score >= 90).",
)
