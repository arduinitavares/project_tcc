# orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/agent.py
"""
StoryDraftAgent - Generates a single INVEST-compliant user story from a feature.

This agent receives ONE feature at a time and generates ONE user story.
Output is stored in state['story_draft'] for the next agent in the pipeline.
"""

import os
from pathlib import Path

import dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body
from utils.schemes import StoryDraft, StoryDraftInput

# --- Load Environment ---
dotenv.load_dotenv()

# --- Pydantic Schemas ---
# StoryDraftInput and StoryDraft are centralized in utils.schemes

# --- Model ---
model = LiteLlm(
    model=get_model_id("story_draft"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)


def create_story_draft_agent() -> LlmAgent:
    """Create a new StoryDraftAgent instance.

    Returns:
        LlmAgent: Fresh StoryDraftAgent instance.
    """
    return LlmAgent(
        name="StoryDraftAgent",
        model=model,
        instruction=load_instruction(Path(__file__).parent / "instructions.txt"),
        description="Generates a single user story draft from a feature.",
        input_schema=StoryDraftInput,
        output_key="story_draft",  # Stores output in state['story_draft']
        output_schema=StoryDraft,  # Pydantic schema for structured output
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


# --- Agent Definition ---
story_draft_agent = create_story_draft_agent()
