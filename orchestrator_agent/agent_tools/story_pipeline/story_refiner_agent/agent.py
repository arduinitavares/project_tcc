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
from typing import Annotated, Optional

import dotenv
from pydantic import BaseModel, Field, model_validator, ValidationInfo
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext

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
    model="openrouter/openai/gpt-4o-mini",  # Refinement model
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)

# --- Instructions ---
STORY_REFINER_INSTRUCTION = """You are an expert Agile coach specializing in refining user stories.

# ⚠️ MANDATORY FIRST STEP - DO THIS BEFORE ANYTHING ELSE
Before taking any action, you MUST check BOTH validation results:
1. `validation_result.suggestions` (INVEST feedback)
2. `spec_validation_result.suggestions` (Spec feedback)

Combine them into a single list of required edits.
- If ANY suggestions exist: You have actionable feedback.
- If `spec_validation_result.is_compliant` is FALSE: You must fix spec violations.

# YOUR TASK
Based on the validation feedback, decide:
1. If score >= 90 AND ALL suggestions are EMPTY: Output story as-is (is_valid=True, refinement_applied=False).
2. If suggestions exist (INVEST or Spec): Apply ALL suggestions.
3. If score < 90: Apply all feedback to improve the story.

# INPUT (from state)
- `story_draft`: The original story JSON
- `validation_result`: INVEST feedback (is_valid, score, suggestions)
- `spec_validation_result`: Technical spec feedback (is_compliant, issues, suggestions)
- `current_feature`: The feature context

# DECISION LOGIC

## CASE 1: Score >= 90 AND suggestions is EMPTY (len = 0)
1. Keep the story exactly as is.
2. Set `is_valid` = true.
3. Set `refinement_applied` = false.
4. Set `refinement_notes` = "No changes needed - story passed validation with score >= 90."

## CASE 2: Score >= 90 BUT suggestions is NOT EMPTY (len > 0)
1. Apply each suggestion from validation_result.suggestions.
2. Incorporate edge cases, error handling, or clarifications mentioned.
3. Output refined story with improvements.
4. Set `is_valid` = true.
5. Set `refinement_applied` = true.

## CASE 3: Score < 90
1. Read each issue in validation_result.issues.
2. Apply suggestions from validation_result.suggestions.
3. Preserve what was good (high INVEST scores).
4. Fix what was flagged (low INVEST scores).
5. Set `is_valid` = true (assuming you fixed the issues).
6. Set `refinement_applied` = true.

# REFINEMENT GUIDELINES

## For "Missing acceptance criteria":
Add 3-5 specific, testable criteria using this format:
- User can [action]
- System displays [information]
- When [condition], then [result]

## For "Story too large":
- Focus on the SMALLEST valuable increment
- Remove scope that could be separate stories
- Ensure it fits in 1-5 story points

## For "Description incomplete":
Complete the format: "As a [specific persona], I want [concrete action] so that [clear benefit]."

## For "Not testable":
Rewrite criteria to be verifiable:
- BAD: "User has a good experience"
- GOOD: "Page loads in under 2 seconds"

## For "Depends on other stories":
Rephrase to be self-contained, or note that dependency is acceptable.

# OUTPUT
Return the structured refinement result.
"""

# --- Agent Definition ---
story_refiner_agent = LlmAgent(
    name="StoryRefinerAgent",
    model=model,
    instruction=STORY_REFINER_INSTRUCTION,
    description="Refines a user story based on validation feedback.",
    output_key="refinement_result",  # Stores output in state['refinement_result']
    output_schema=RefinementResult,
)
