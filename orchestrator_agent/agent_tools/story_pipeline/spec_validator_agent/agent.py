"""
SpecValidatorAgent - Validates a user story against technical specifications.

This agent receives a story draft and the product's technical specification.
It determines if the story complies with explicit constraints (must/shall/required).

Output is stored in state['spec_validation_result'].
"""

import os
import dotenv
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# --- Load Environment ---
dotenv.load_dotenv()

class SpecValidationResult(BaseModel):
    """Structured specification compliance output."""
    is_compliant: bool = Field(..., description="True if story complies with all explicit spec requirements")
    issues: list[str] = Field(default_factory=list, description="Specific spec violations found. EMPTY [] if compliant.")
    suggestions: list[str] = Field(default_factory=list, description="Actionable edits to fix spec violations. MUST be EMPTY [] if compliant.")
    verdict: str = Field(..., description="Brief summary of spec compliance check")

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
If `technical_spec` is EMPTY, MISSING, or too vague:
- Return `is_compliant: true`
- Return `suggestions: []`
- Verdict: "No technical spec provided" or "No relevant constraints found"

## 2. CHECK FOR EXPLICIT VIOLATIONS
Only flag issues that contradict **EXPLICIT** requirements in the text.
Look for keywords: "MUST", "SHALL", "REQUIRED", "ALWAYS", "NEVER".

Examples of violations:
- Spec: "System MUST use PostgreSQL" -> Story: "Store data in MongoDB" (VIOLATION)
- Spec: "All APIs MUST return JSON" -> Story: "Return XML response" (VIOLATION)
- Spec: "Artifact X is REQUIRED" -> Story: Missing Artifact X (VIOLATION)

## 3. CHECK FOR MISSING REQUIRED ARTIFACTS
If the spec explicitly says a story of this type MUST produce a specific output or artifact, and the story omits it, flag it.

## 4. CONSERVATIVE BEHAVIOR
- Do NOT infer requirements that aren't written.
- Do NOT re-score INVEST principles (that's another agent's job).
- Do NOT flag stylistic preferences, only spec violations.

# OUTPUT FORMAT
You MUST output valid JSON matching the SpecValidationResult schema:
```json
{
  "is_compliant": <boolean>,
  "issues": ["<violation 1>", "<violation 2>"],
  "suggestions": ["<actionable edit 1>", "<actionable edit 2>"],
  "verdict": "<summary>"
}
```

# CRITICAL RULES FOR `suggestions`
- **MUST be EMPTY []** if `is_compliant` is true.
- If `is_compliant` is false, provide specific instructions to fix the violation.
- Example Suggestion: "Change database from MongoDB to PostgreSQL as per spec."

# DEVELOPER NOTE
To extend this validator later, consider adding an invariant registry or specific rule sets for different project types (e.g. P&ID, SCADA, Web App). For now, rely on text inference from the provided spec.
"""

# --- Agent Definition ---
spec_validator_agent = LlmAgent(
    name="SpecValidatorAgent",
    model=model,
    instruction=SPEC_VALIDATOR_INSTRUCTION,
    description="Validates story compliance with technical specifications.",
    output_key="spec_validation_result",
    output_schema=SpecValidationResult,
)
