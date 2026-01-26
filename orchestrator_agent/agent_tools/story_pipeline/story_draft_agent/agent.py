# orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/agent.py
"""
StoryDraftAgent - Generates a single INVEST-compliant user story from a feature.

This agent receives ONE feature at a time and generates ONE user story.
Output is stored in state['story_draft'] for the next agent in the pipeline.
"""

import os
from typing import Annotated, Optional

import dotenv
from pydantic import BaseModel, Field, field_validator
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# --- Load Environment ---
dotenv.load_dotenv()

# --- Pydantic Model ---
class StoryDraft(BaseModel):
    """
    Schema for a User Story draft.
    """
    feature_id: Annotated[int, Field(description="The ID of the feature this story belongs to.")]
    feature_title: Annotated[str, Field(description="The title of the feature.")]
    title: Annotated[str, Field(description="Short, action-oriented title for the story.")]
    description: Annotated[str, Field(
        description="The story narrative in the format: 'As a <persona>, I want <action> so that <benefit>.'"
    )]
    acceptance_criteria: Annotated[str, Field(
        description="A list of 3-5 specific, testable criteria, each starting with '- '."
    )]
    story_points: Annotated[Optional[int], Field(
        description="Estimated effort (1-8 points). Null if not estimable."
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

# --- Instructions ---
STORY_DRAFT_INSTRUCTION = """You are an expert Agile Product Owner specializing in writing user stories.

# YOUR TASK
Generate ONE high-quality user story for the given feature.

# INPUT (from state)
- `current_feature`: JSON object with:
  - feature_id, feature_title, theme, epic
  - time_frame: "Now" (current sprint focus), "Next" (near-term), or "Later" (future)
  - theme_justification: Why this theme exists in the roadmap
  - sibling_features: Other features in the same theme
- `product_context`: JSON with product_id, product_name, vision, time_frame
- `user_persona`: The MANDATORY target user persona. The story MUST use this exact persona.
- `story_preferences`: Any user preferences (story points yes/no, etc.)
- `refinement_feedback`: If this is a retry, contains feedback from validator (otherwise empty)
- `technical_spec`: (OPTIONAL) Full technical specification document with domain context

# 📄 USING THE TECHNICAL SPECIFICATION
If `technical_spec` is provided and non-empty:
1. **Use domain terminology** from the spec in acceptance criteria (e.g., "P&ID", "tag", "primitive", "confidence score")
2. **Reference workflows** described in the spec when writing the "so that" clause
3. **Align acceptance criteria** with concepts mentioned in the spec (e.g., "review-first", "stage-gated", "gold snapshot")
4. **Understand user context** - the spec explains what the persona actually does day-to-day
5. **DO NOT invent features** not in the spec - stay within the documented scope

If `technical_spec` is empty or not provided:
- Generate the story based on feature_title and product_vision alone
- Use generic but sensible acceptance criteria

# ⚠️ CRITICAL PERSONA ENFORCEMENT RULES
The `user_persona` field is MANDATORY and NON-NEGOTIABLE:
1. Use the exact persona in "As a {user_persona}, I want..." format
2. DO NOT substitute with generic roles even if the feature involves:
   - UI interaction → Still use provided persona, NOT "frontend developer"
   - Configuration → Still use provided persona, NOT "software engineer"
   - Data validation → Still use provided persona, NOT "data annotator"
   - Review workflows → Still use provided persona, NOT "QA engineer"
3. DO NOT generalize to "user" or "customer" unless that's the actual persona provided
4. The persona reflects WHO uses the feature, not WHAT the feature does
5. If persona is "automation engineer", they may perform UI work, config, validation, AND review tasks

WRONG EXAMPLES:
- Provided: "automation engineer" → Story uses: "software engineer" ❌
- Provided: "automation engineer" → Story uses: "data annotator" ❌
- Provided: "engineering QA reviewer" → Story uses: "QA engineer" ❌

CORRECT EXAMPLE:
- Provided: "automation engineer" → Story uses: "automation engineer" ✅

# INVEST PRINCIPLES (follow strictly)
- **Independent**: Story can be developed without depending on other stories
- **Negotiable**: Details can be discussed, not a rigid contract
- **Valuable**: Delivers clear value to the user
- **Estimable**: Small enough to estimate accurately
- **Small**: Fits in a single sprint (1-8 story points)
- **Testable**: Acceptance criteria are verifiable

# TIME-FRAME ALIGNMENT
- If time_frame is "Now": Story should be immediately actionable and not require other unbuilt features
- If time_frame is "Next": Story can assume "Now" features exist
- If time_frame is "Later": Story can reference future capabilities, acknowledge dependencies
- The story's scope and assumptions should match its time-frame

# ACCEPTANCE CRITERIA RULES
- Write 3-5 specific, testable criteria
- Each starts with "- " (dash space)
- Use action verbs: "User can...", "System displays...", "Error message shows..."
- Include edge cases when relevant
- Be specific, not vague

# IF REFINEMENT_FEEDBACK IS PROVIDED
The validator found issues with your previous attempt. Address them:
- Read the feedback carefully
- Fix the specific issues mentioned
- Keep what was good, improve what was flagged
"""

# --- Agent Definition ---
story_draft_agent = LlmAgent(
    name="StoryDraftAgent",
    model=model,
    instruction=STORY_DRAFT_INSTRUCTION,
    description="Generates a single user story draft from a feature.",
    output_key="story_draft",  # Stores output in state['story_draft']
    output_schema=StoryDraft,  # Pydantic schema for structured output
)
