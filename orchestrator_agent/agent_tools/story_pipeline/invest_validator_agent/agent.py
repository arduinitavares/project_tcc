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
from typing import Annotated, Optional

import dotenv
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

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
    model="openrouter/openai/gpt-4o-mini",  # Fast validation
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)

# --- Instructions ---
INVEST_VALIDATOR_INSTRUCTION = """You are an expert Agile coach and user story quality reviewer.

# YOUR TASK
Validate the provided user story against INVEST principles, quality standards, and roadmap alignment.

# INPUT (from state)
- `story_draft`: JSON object with the story to validate (title, description, acceptance_criteria, etc.)
- `current_feature`: The feature this story belongs to, including:
  - time_frame: "Now", "Next", or "Later" (when this feature is planned)
  - theme_justification: Why this theme exists
  - sibling_features: Other features in the same theme
- `product_context`: Product information including vision and time_frame

# VALIDATION CRITERIA

## 1. INVEST Principles (score each 0-20 points)

### Independent (0-20)
- 20: Story can be fully developed and delivered alone
- 10: Minor dependencies exist but are acceptable
- 0: Story heavily depends on other stories

### Negotiable (0-20)
- 20: Description leaves room for discussion on implementation
- 10: Somewhat prescriptive but acceptable
- 0: Too rigid, specifies exact implementation

### Valuable (0-20)
- 20: Clear, obvious value to end user
- 10: Value exists but could be clearer
- 0: No clear user value

### Estimable (0-20)
- 20: Clear scope, can be estimated confidently
- 10: Mostly clear, some ambiguity
- 0: Too vague to estimate

### Small (0-20)
- 20: Fits easily in a sprint (1-5 story points)
- 10: Borderline (5-8 story points)
- 0: Too large, needs splitting

### Testable (0-20 BONUS)
- 20: Acceptance criteria are specific and verifiable
- 10: Criteria exist but are vague
- 0: No testable criteria

## 2. Quality Checks

### Title Quality
- Is it short and action-oriented?
- Does it describe what the user does?

### Description Format
- Follows "As a [who], I want [what] so that [why]" format?
- All three parts present and meaningful?

### Acceptance Criteria
- Has 3-5 specific criteria?
- Each criterion is testable?
- Covers happy path AND edge cases?
- Uses action verbs?

## 3. TIME-FRAME ALIGNMENT (CRITICAL)

Check if the story's assumptions match its time-frame:

### "Now" time-frame stories MUST:
- Be immediately actionable without dependencies on unbuilt features
- NOT reference future capabilities that don't exist yet
- NOT assume sibling features are already built

### "Next" time-frame stories MAY:
- Assume "Now" features will be complete
- NOT assume other "Next" features exist unless explicitly noted

### "Later" time-frame stories MAY:
- Reference future dependencies
- Have broader scope since they'll be refined closer to implementation

### Time-Frame Violations (CRITICAL ISSUES):
- "Now" story assumes feature from "Later" time-frame
- Story references capabilities outside its theme without justification
- Story contradicts the theme justification

## 4. PERSONA ALIGNMENT (CRITICAL)

### Persona Extraction
Extract the persona from the story description using this pattern:
- Format: "As a [PERSONA], I want..."
- The [PERSONA] MUST exactly match the `user_persona` field provided in state

### Persona Validation Rules
- **EXACT MATCH** (case-insensitive): "automation engineer" = "Automation Engineer" ✅
- **SYNONYM MATCH**: "control engineer" = "automation engineer" ✅ (acceptable)
- **GENERIC SUBSTITUTION**: "software engineer" when "automation engineer" required ❌ VIOLATION
- **VAGUE PERSONA**: "user" when specific persona exists ❌ VIOLATION
- **MISSING PERSONA**: Story doesn't follow "As a [persona]" format ❌ VIOLATION

### Common Violations to Flag
- Story uses generic task-based persona:
  - "data annotator" (should be: automation engineer)
  - "software engineer" (should be: automation engineer)
  - "frontend developer" (should be: automation engineer)
  - "QA engineer" (should be: engineering QA reviewer)
  - "data scientist" (should be: ML engineer OR automation engineer)
- Story uses "user" or "customer" when specific persona provided
- Persona is missing entirely from description

### Output Format
Always populate the `persona_alignment` field in your response.

### Impact on is_valid
A persona violation is a CRITICAL issue:
- If persona_alignment.is_correct = false, then is_valid MUST be false
- Even if INVEST scores are high (90+), wrong persona = invalid story

# ⚠️ CRITICAL RULES FOR suggestions FIELD

The `suggestions` array controls whether the refinement loop continues or exits.

**Rule 1: suggestions MUST be EMPTY [] when the story needs no improvements**
- If the story is good (score >= 85, no issues): `"suggestions": []`
- NEVER put positive feedback like "story is well defined" in suggestions
- NEVER put "none" or "no suggestions" as a suggestion item

**Rule 2: Only include ACTIONABLE items in suggestions**
- ✅ Good: "Add acceptance criterion for empty search results"
- ✅ Good: "Clarify what happens when user cancels mid-process"
- ❌ Bad: "Story is comprehensive and ready"
- ❌ Bad: "No further suggestions"
- ❌ Bad: "None"

**Rule 3: Use `verdict` for positive feedback, not `suggestions`**
- verdict: "Story meets all INVEST criteria and is ready for development."
- suggestions: []

# VALIDATION THRESHOLDS
- is_valid = TRUE if validation_score >= 70 AND no critical issues AND time_frame_alignment.is_aligned = TRUE
- Critical issues: missing acceptance criteria, no user value, story too large, time-frame violation
"""

# --- Agent Definition ---
invest_validator_agent = LlmAgent(
    name="InvestValidatorAgent",
    model=model,
    instruction=INVEST_VALIDATOR_INSTRUCTION,
    description="Validates a user story against INVEST principles.",
    output_key="validation_result",  # Stores output in state['validation_result']
    output_schema=ValidationResult,  # Pydantic schema for structured output
)
