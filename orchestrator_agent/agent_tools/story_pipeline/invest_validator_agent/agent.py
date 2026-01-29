# orchestrator_agent/agent_tools/story_pipeline/invest_validator_agent/agent.py
"""
InvestValidatorAgent - Validates a user story against INVEST principles.

This agent receives a story draft and validates it, providing:
- is_valid: boolean
- validation_score: 0-100
- issues: list of specific problems found
- suggestions: actionable feedback for refinement (EMPTY if none needed)

Output is stored in state['validation_result'] for the next agent.
"""

import os
from pathlib import Path
from typing import Annotated, Optional

import dotenv
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body

# --- Load Environment ---
dotenv.load_dotenv()

# Define a constrained alias 
Score = Annotated[int, Field(ge=0, le=20, description="Score from 0 to 20")]

class InvestScores(BaseModel):
    """INVEST principle scores (0-20 each)."""
    independent: Score
    negotiable: Score
    valuable: Score
    estimable: Score
    small: Score
    testable: Score


class TimeFrameAlignment(BaseModel):
    """Time-frame alignment check result."""
    is_aligned: Annotated[bool, Field(description="True if story matches its time-frame")]
    issues: Annotated[list[str], Field(default_factory=list, description="Time-frame violation issues (empty if aligned)")]

    @model_validator(mode='after')
    def validate_consistency(self) -> 'TimeFrameAlignment':
        if not self.is_aligned and not self.issues:
            raise ValueError("Logical inconsistency: is_aligned=False but issues list is empty.")
        if self.is_aligned and self.issues:
            raise ValueError("Logical inconsistency: is_aligned=True but issues list is not empty.")
        return self


class PersonaAlignment(BaseModel):
    """Persona correctness check result."""
    is_correct: Annotated[bool, Field(description="True if story uses the required persona")]
    expected_persona: Annotated[str, Field(description="The persona that should be used")]
    actual_persona: Annotated[Optional[str], Field(default=None, description="The persona extracted from story")]
    issues: Annotated[list[str], Field(default_factory=list, description="Persona mismatch details (empty if correct)")]

    @model_validator(mode='after')
    def validate_consistency(self) -> 'PersonaAlignment':
        if not self.is_correct and not self.issues:
            raise ValueError("Logical inconsistency: is_correct=False but issues list is empty.")
        if self.is_correct and self.issues:
            raise ValueError("Logical inconsistency: is_correct=True but issues list is not empty.")
        return self


class ValidationResult(BaseModel):
    """Structured validation output - enables deterministic checking."""
    is_valid: Annotated[bool, Field(description="True if story passes validation (score >= 70, no critical issues, time-frame aligned)")]
    validation_score: Annotated[int, Field(ge=0, le=100, description="Overall quality score 0-100")]
    invest_scores: Annotated[InvestScores, Field(description="Individual INVEST principle scores")]
    time_frame_alignment: Annotated[TimeFrameAlignment, Field(description="Time-frame alignment result")]
    persona_alignment: Annotated[PersonaAlignment, Field(description="Persona correctness validation result")]
    issues: Annotated[list[str], Field(default_factory=list, description="Specific problems found. EMPTY [] if no issues.")]
    suggestions: Annotated[list[str], Field(default_factory=list, description="Actionable improvements. MUST be EMPTY [] if no improvements needed. Never put positive feedback here.")]
    verdict: Annotated[str, Field(description="Brief summary of validation result")]

    @model_validator(mode='after')
    def validate_model_consistency(self) -> 'ValidationResult':
        """Enforce validation logic consistency across all fields."""

        # Check Persona Alignment impact
        if not self.persona_alignment.is_correct and self.is_valid:
            raise ValueError("Logical inconsistency: is_valid=True but persona_alignment.is_correct=False. A persona mismatch is a critical failure.")

        # Check Time Frame Alignment impact
        if not self.time_frame_alignment.is_aligned and self.is_valid:
            raise ValueError("Logical inconsistency: is_valid=True but time_frame_alignment.is_aligned=False. A time-frame violation is a critical failure.")

        # Check Score impact
        if self.validation_score < 70 and self.is_valid:
            raise ValueError(f"Logical inconsistency: is_valid=True but validation_score={self.validation_score} (must be >= 70).")

        # Rule 1: suggestions MUST be EMPTY [] when the story needs no improvements
        # "If the story is good (score >= 85, no issues): 'suggestions': []"
        if self.validation_score >= 85 and not self.issues and self.suggestions:
            raise ValueError("Logical inconsistency: High score (>=85) and no issues, but 'suggestions' is not empty. If the story is valid and high-quality, suggestions must be empty.")

        return self


# --- Model ---
model = LiteLlm(
    model=get_model_id("invest_validator"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)

# --- Agent Definition ---
invest_validator_agent = LlmAgent(
    name="InvestValidatorAgent",
    model=model,
    instruction=load_instruction(Path(__file__).parent / "instructions.txt"),
    description="Validates a user story against INVEST principles.",
    output_key="validation_result",  # Stores output in state['validation_result']
    output_schema=ValidationResult,  # Pydantic schema for structured output
)
