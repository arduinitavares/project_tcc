# orchestrator_agent/agent_tools/story_pipeline/pipeline.py
"""
Story Validation Pipeline - LoopAgent + SequentialAgent hybrid.

Architecture:
┌──────────────────────────────────────────────────────────────┐
│              LoopAgent (max_iterations=4)                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │            SequentialAgent (per story)                  │ │
│  │                                                         │ │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │ │
│  │  │ StoryDraft  │ → │    SPEC     │ → │ StoryRefine │   │ │
│  │  │   Agent     │   │  Validator  │   │   Agent     │   │ │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   │ │
│  │        ↓                 ↓                 ↓            │ │
│  │   state['draft']   state['spec']    state['refined']   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                              ↓                               │
│    Iteration 1: Draft story (INVEST built-in), spec check    │
│    Iteration 2+: Refine based on spec feedback               │
└──────────────────────────────────────────────────────────────┘

The pipeline processes ONE feature → ONE story at a time.
INVEST principles are enforced by the Draft Agent's instructions.
Spec Validator ensures domain-specific artifact compliance.
"""

from google.adk.agents import SequentialAgent

from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import (
    story_draft_agent,
)
from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import (
    spec_validator_agent,
)
from orchestrator_agent.agent_tools.story_pipeline.story_refiner_agent.agent import (
    story_refiner_agent,
)
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent, ConditionalLoopAgent


# --- Sequential Pipeline ---
# Runs: Draft → SPEC Validate → Refine in strict order
# SPEC validator ensures domain-specific artifact compliance.
# Each agent is wrapped in SelfHealingAgent to automatically retry on Pydantic validation errors.
story_sequential_pipeline = SequentialAgent(
    name="StorySequentialPipeline",
    sub_agents=[
        SelfHealingAgent(agent=story_draft_agent, max_retries=3),
        SelfHealingAgent(agent=spec_validator_agent, max_retries=3),
        SelfHealingAgent(agent=story_refiner_agent, max_retries=3),
    ],
    description="Drafts a story, validates spec, and refines if needed.",
)


# --- Loop Agent ---
# Wraps the sequential pipeline to retry if validation fails.
# REPLACED standard LoopAgent with ConditionalLoopAgent to enable early exit
# without tool calls, checking 'refinement_result.is_valid'.
story_validation_loop = ConditionalLoopAgent(
    name="StoryValidationLoop",
    agent=story_sequential_pipeline,
    max_iterations=4,  # Safety limit - allows spec feedback refinement
    exit_condition_key="refinement_result.is_valid",
    description="Loops through story creation until spec-compliant (exits when no suggestions remain).",
)
