# orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/agent.py
"""
StoryDraftAgent - Generates a single INVEST-compliant user story from a feature.

This agent receives ONE feature at a time and generates ONE user story.
Output is stored in state['story_draft'] for the next agent in the pipeline.
"""

import os
from pathlib import Path
from typing import Annotated, Optional

import dotenv
from pydantic import BaseModel, Field, field_validator
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction

# --- Load Environment ---
dotenv.load_dotenv()

# --- Pydantic Model ---
class StoryDraft(BaseModel):
    """
    Schema for a User Story draft.
    NOTE: feature_id and feature_title are NOT part of this schema.
    They are preserved from input state to prevent LLM override causing data corruption.
    """
    title: Annotated[str, Field(description="Short, action-oriented title for the story.")]
    description: Annotated[str, Field(
        description="The story narrative in the format: 'As a <persona>, I want <action> so that <benefit>.'"
    )]
    acceptance_criteria: Annotated[str, Field(
        description="A list of 3-5 specific, testable criteria, each starting with '- '."
    )]
    story_points: Annotated[Optional[int], Field(
        description="Estimated effort (1-8 points). Null if not estimable or if story points are disabled."
    )]

    @field_validator('description', mode='after')
    @classmethod
    def validate_description_format(cls, v: str) -> str:
        """Enforce standard user story format."""
        if not v.lower().startswith("as a"):
            raise ValueError("Story description must start with 'As a ...'")
        if " i want " not in v.lower():
            raise ValueError("Story description must contain '... I want ...'")
        if " so that " not in v.lower():
            raise ValueError("Story description must contain '... so that ...'")
        return v

    @field_validator('story_points', mode='after')
    @classmethod
    def validate_story_points(cls, v: Optional[int]) -> Optional[int]:
        """Enforce story point limits if provided."""
        if v is not None and (v < 1 or v > 8):
            raise ValueError("Story points must be between 1 and 8 (INVEST principle: Small).")
        return v

# --- Model ---
model = LiteLlm(
    model="openrouter/openai/gpt-4.1-mini",  # Faster model for drafting
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)

# --- Agent Definition ---
story_draft_agent = LlmAgent(
    name="StoryDraftAgent",
    model=model,
    instruction=load_instruction(Path(__file__).parent / "instructions.txt"),
    description="Generates a single user story draft from a feature.",
    output_key="story_draft",  # Stores output in state['story_draft']
    output_schema=StoryDraft,  # Pydantic schema for structured output
)
