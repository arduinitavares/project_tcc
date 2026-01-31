# orchestrator_agent/agent_tools/story_pipeline/story_refiner_agent/agent.py
"""
StoryRefinerAgent - Refines a user story based on validation feedback.

This agent receives:
- The original story draft
- Validation feedback with issues and suggestions

It outputs a refined story OR marks the story as final if already valid.
Also sets `is_valid` in state to control the loop exit condition.
"""

import os
from pathlib import Path
from typing import Annotated, Optional

import dotenv
from pydantic import BaseModel, Field, model_validator, ValidationInfo
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body

# Import StoryDraft schema
from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import StoryDraft

# --- Load Environment ---
dotenv.load_dotenv()

# --- Pydantic Model ---
class RefinementResult(BaseModel):
    """
    Result of the story refinement process.
    """
    refined_story: Annotated[StoryDraft, Field(description="The refined user story.")]
    is_valid: Annotated[bool, Field(description="True if the story is considered valid and ready.")]
    refinement_applied: Annotated[bool, Field(description="True if changes were made to the original draft.")]
    refinement_notes: Annotated[str, Field(description="Explanation of changes or why no changes were needed.")]

    @model_validator(mode='after')
    def validate_consistency(self) -> 'RefinementResult':
        """Ensure logic consistency."""
        # Logic: If no refinement was applied, notes should likely indicate "no changes" or "valid".
        if self.refinement_applied is False:
             notes = self.refinement_notes
             lower_notes = notes.lower()
             valid_phrases = ["no changes", "passed validation", "valid", "as is", "already good"]
             if not any(phrase in lower_notes for phrase in valid_phrases):
                  # Raise error to enforce self-consistency
                  raise ValueError(
                      f"Logical inconsistency: refinement_applied=False but notes do not indicate validity. "
                      f"Notes: '{notes}'. Expected phrases: {valid_phrases}"
                  )
        return self

# --- Model ---
model = LiteLlm(
    model=get_model_id("story_refiner"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)

# --- Agent Definition ---
story_refiner_agent = LlmAgent(
    name="StoryRefinerAgent",
    model=model,
    instruction=load_instruction(Path(__file__).parent / "instructions.txt"),
    description="Refines a user story based on validation feedback.",
    output_key="refinement_result",  # Stores output in state['refinement_result']
    output_schema=RefinementResult,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
