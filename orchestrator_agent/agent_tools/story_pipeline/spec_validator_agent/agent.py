"""
SpecValidatorAgent - Validates a user story against technical specifications.

This agent receives a story draft and the product's technical specification.
It determines if the story complies with explicit constraints (must/shall/required).

The agent uses Pydantic V2 field validators to enforce logical consistency.
When validation fails, Pydantic raises descriptive errors that the calling
pipeline can use to trigger retries or provide feedback to upstream agents.
"""

import os
import dotenv
from typing import Annotated
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# --- Load Environment ---
dotenv.load_dotenv()

class SpecValidationResult(BaseModel):
    """
    Structured specification compliance output.
    
    Enforces logical consistency via Pydantic validators:
    - Compliant stories cannot have issues or suggestions
    - Non-compliant stories must have at least one issue
    
    Validation failures trigger LLM retries automatically.
    """
    is_compliant: Annotated[
        bool, 
        Field(description="True if story complies with all explicit spec requirements")
    ]
    issues: Annotated[
        list[str], 
        Field(default_factory=list, description="Specific spec violations found. Empty if compliant.")
    ]
    suggestions: Annotated[
        list[str], 
        Field(default_factory=list, description="Actionable edits to fix spec violations. Empty if compliant.")
    ]
    verdict: Annotated[
        str, 
        Field(description="Brief summary of spec compliance check")
    ]
    
    @field_validator('issues', 'suggestions', mode='after')
    @classmethod
    def validate_compliant_has_no_issues(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """
        Enforce: If is_compliant is True, issues and suggestions MUST be empty.
        
        This validator runs after field assignment to check logical consistency.
        Triggers LLM retry if violated.
        """
        # Access the is_compliant field from the context
        if info.data.get('is_compliant') is True and len(v) > 0:
            field_name = info.field_name
            raise ValueError(
                f"Logical inconsistency: is_compliant=True but {field_name} is not empty. "
                f"When a story is compliant, there should be no {field_name}. "
                f"Either set is_compliant=False or clear the {field_name} list."
            )
        return v
    
    @field_validator('issues', mode='after')
    @classmethod
    def validate_non_compliant_has_issues(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """
        Enforce: If is_compliant is False, issues MUST NOT be empty.
        
        Triggers LLM retry if violated.
        """
        if info.data.get('is_compliant') is False and len(v) == 0:
            raise ValueError(
                "Logical inconsistency: is_compliant=False but issues list is empty. "
                "If a story is non-compliant, you must specify at least one issue."
            )
        return v

# --- Model ---
model = LiteLlm(
    model="openrouter/openai/gpt-4o-mini",  # Fast validation
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)

# --- Instructions ---
SPEC_VALIDATOR_INSTRUCTION = """You are a Technical Compliance Officer ensuring user stories match the Technical Specification.

# YOUR TASK
Validate the provided `story_draft` against the `technical_spec`.

# INPUT (from state)
- `story_draft`: The story to validate (title, description, acceptance_criteria)
- `technical_spec`: The technical specification document (may be empty)
- `current_feature`: Feature context
- `user_persona`: Target persona

# VALIDATION RULES

## 1. DEFAULT TO COMPLIANT
If `technical_spec` is EMPTY, MISSING, or too vague, mark the story as compliant.

Reasoning: Without explicit constraints, there is nothing to violate.

## 2. CHECK FOR EXPLICIT VIOLATIONS
Only flag issues that contradict **EXPLICIT** requirements in the specification text.

Look for definitive requirement keywords:
- "MUST", "SHALL", "REQUIRED"
- "ALWAYS", "NEVER"
- "MANDATORY", "PROHIBITED"

Examples of violations:
- Spec: "System MUST use PostgreSQL" → Story: "Store data in MongoDB" (VIOLATION)
- Spec: "All APIs MUST return JSON" → Story: "Return XML response" (VIOLATION)
- Spec: "Artifact X is REQUIRED" → Story: Missing Artifact X (VIOLATION)

## 3. CHECK FOR MISSING REQUIRED ARTIFACTS
If the spec explicitly states a story of this type MUST produce a specific output or artifact, and the story omits it, flag the omission.

## 4. CONSERVATIVE BEHAVIOR
- Do NOT infer requirements that aren't explicitly written
- Do NOT re-score INVEST principles (that's another agent's job)
- Do NOT flag stylistic preferences or recommendations
- Only flag hard constraints that would fail compliance audits

## 5. PROVIDE ACTIONABLE SUGGESTIONS
When marking a story as non-compliant, provide specific, actionable edits to resolve each violation.

Example: "Change the database technology from MongoDB to PostgreSQL to comply with spec requirement in Section 3.2."

# DEVELOPER NOTE
To extend this validator later, consider adding an invariant registry or specific rule sets for different project types (e.g. P&ID, SCADA, Web App). For now, rely on text inference from the provided spec.
"""

# --- Agent Definition ---
spec_validator_agent = LlmAgent(
    name="SpecValidatorAgent",
    model=model,
    instruction=SPEC_VALIDATOR_INSTRUCTION,
    description="Validates story compliance with technical specifications using Pydantic-enforced logic checks.",
    output_key="spec_validation_result",
    output_schema=SpecValidationResult,
)
