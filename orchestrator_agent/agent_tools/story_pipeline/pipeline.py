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
from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import (
    spec_validator_agent,
)
from orchestrator_agent.agent_tools.story_pipeline.story_refiner_agent.agent import (
    story_refiner_agent,
)
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent


# --- Sequential Pipeline ---
# Runs: Draft → INVEST Validate → SPEC Validate → Refine in strict order
# Each agent is wrapped in SelfHealingAgent to automatically retry on Pydantic validation errors.
story_sequential_pipeline = SequentialAgent(
    name="StorySequentialPipeline",
    sub_agents=[
        SelfHealingAgent(story_draft_agent, max_retries=3),
        SelfHealingAgent(invest_validator_agent, max_retries=3),
        SelfHealingAgent(spec_validator_agent, max_retries=3),
        SelfHealingAgent(story_refiner_agent, max_retries=3),
    ],
    description="Drafts a story, validates it, and refines if needed.",
)


# --- Loop Agent ---
# Wraps the sequential pipeline to retry if validation fails
# Exits EARLY when refiner calls exit_loop (score >= 90 AND no suggestions)
# max_iterations is a safety limit, not the typical case
story_validation_loop = LoopAgent(
    name="StoryValidationLoop",
    sub_agents=[story_sequential_pipeline],
    max_iterations=4,  # Safety limit - increased to allow feedback refinement at high scores
    description="Loops through story creation until INVEST-valid (exits early when score >= 90 AND no suggestions).",
)
