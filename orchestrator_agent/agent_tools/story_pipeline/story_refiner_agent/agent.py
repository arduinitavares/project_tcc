# orchestrator_agent/agent_tools/story_pipeline/story_refiner_agent/agent.py
"""
StoryRefinerAgent - Refines a user story based on validation feedback.

This agent receives:
- The original story draft
- Validation feedback with issues and suggestions

It outputs a refined story OR marks the story as final if already valid.
Also sets `is_valid` in state to control the loop exit condition.

Uses `exit_loop` tool to signal early termination when story is good enough.
"""

import os

import dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext

# --- Load Environment ---
dotenv.load_dotenv()

# --- Model ---
model = LiteLlm(
    model="openrouter/openai/gpt-4o-mini",  # Refinement model
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)


# --- Exit Loop Tool ---
def exit_loop(tool_context: ToolContext) -> dict[str, bool | str]:
    """
    Call this tool to signal that the story is COMPLETE and no more refinement iterations are needed.
    
    ONLY call this when ALL conditions are met:
    - INVEST validation_score >= 90 (high quality)
    - INVEST suggestions is EMPTY (no actionable feedback remaining)
    - SPEC validation is_compliant is TRUE
    - SPEC suggestions is EMPTY
    
    Do NOT call this if there are still actionable suggestions to apply.
    Apply the suggestions first, then exit on the next iteration.
    
    This will immediately stop the refinement loop.
    """
    # Helper to parse JSON from state
    def parse_state_json(key: str) -> dict:
      val = tool_context.state.get(key)
      if isinstance(val, str):
        import json
        try:
          return json.loads(val)
        except json.JSONDecodeError:
          return {}
      return val if isinstance(val, dict) else {}

    def get_feature_title() -> str:
      current_feature = tool_context.state.get("current_feature")
      if isinstance(current_feature, str):
        import json
        try:
          current_feature = json.loads(current_feature)
        except json.JSONDecodeError:
          current_feature = {}
      if isinstance(current_feature, dict):
        return str(current_feature.get("feature_title") or "")
      return ""

    def set_diag(diag: dict) -> None:
      # Avoid noisy stdout prints (breaks batch logs due to async).
      # Persist a diagnostic record so the runner can surface it deterministically.
      diag.setdefault("feature_title", get_feature_title())
      tool_context.state["exit_loop_diagnostic"] = diag

    # 1. Check INVEST Validation
    validation_result = parse_state_json("validation_result")
    invest_suggestions = validation_result.get("suggestions", [])

    if invest_suggestions and len(invest_suggestions) > 0:
      diag = {
        "loop_exit": False,
        "blocked_by": "invest_suggestions",
        "reason": f"Cannot exit: {len(invest_suggestions)} INVEST suggestions remain.",
        "pending_suggestions": invest_suggestions,
      }
      set_diag(diag)
      return diag

    # 2. Check SPEC Validation
    spec_result = parse_state_json("spec_validation_result")
    spec_suggestions = spec_result.get("suggestions", [])
    is_compliant = spec_result.get("is_compliant", True) # Default to true if missing

    if not is_compliant:
      diag = {
        "loop_exit": False,
        "blocked_by": "spec_non_compliant",
        "reason": "Cannot exit: Story is not compliant with technical spec.",
        "spec_issues": spec_result.get("issues", []),
      }
      set_diag(diag)
      return diag

    if spec_suggestions and len(spec_suggestions) > 0:
      diag = {
        "loop_exit": False,
        "blocked_by": "spec_suggestions",
        "reason": f"Cannot exit: {len(spec_suggestions)} Spec suggestions remain.",
        "pending_suggestions": spec_suggestions,
      }
      set_diag(diag)
      return diag
    
    diag = {"loop_exit": True, "reason": "Story validated successfully"}
    set_diag(diag)
    tool_context.actions.escalate = True
    return diag


# --- Instructions ---
STORY_REFINER_INSTRUCTION = """You are an expert Agile coach specializing in refining user stories.

# ⚠️ MANDATORY FIRST STEP - DO THIS BEFORE ANYTHING ELSE
Before taking any action, you MUST check BOTH validation results:
1. `validation_result.suggestions` (INVEST feedback)
2. `spec_validation_result.suggestions` (Spec feedback)

Combine them into a single list of required edits.
- If ANY suggestions exist: You have actionable feedback → DO NOT call exit_loop
- If `spec_validation_result.is_compliant` is FALSE → DO NOT call exit_loop
- If ALL suggestions are empty AND is_compliant is TRUE → You MAY call exit_loop (if score >= 90)

# YOUR TASK
Based on the validation feedback, decide:
1. If score >= 90 AND ALL suggestions are EMPTY: Call `exit_loop` and output story as-is
2. If suggestions exist (INVEST or Spec): Apply ALL suggestions WITHOUT calling exit_loop
3. If score < 90: Apply all feedback to improve the story

# INPUT (from state)
- `story_draft`: The original story JSON
- `validation_result`: INVEST feedback (is_valid, score, suggestions)
- `spec_validation_result`: Technical spec feedback (is_compliant, issues, suggestions)
- `current_feature`: The feature context

# 🚫 EXIT_LOOP GATE - READ CAREFULLY
**You are FORBIDDEN from calling exit_loop if ANY suggestions exist.**

Even if validation_score is 90, 95, or 100 - if there are suggestions from EITHER validator, you MUST:
1. Apply all suggestions (Spec violations are MANDATORY fixes)
2. Output the refined story
3. Let the loop continue so the next iteration can validate your improvements

**The ONLY time you may call exit_loop:**
- validation_score >= 90 AND
- validation_result.suggestions == [] AND
- spec_validation_result.suggestions == [] AND
- spec_validation_result.is_compliant == true

# DECISION LOGIC

## CASE 1: Score >= 90 AND suggestions is EMPTY (len = 0)
1. Call `exit_loop` tool to stop the loop
2. Output the story as final with no changes
3. Set refinement_applied=false

## CASE 2: Score >= 90 BUT suggestions is NOT EMPTY (len > 0)
⚠️ DO NOT CALL EXIT_LOOP IN THIS CASE
1. Apply each suggestion from validation_result.suggestions
2. Incorporate edge cases, error handling, or clarifications mentioned
3. Output refined story with improvements
4. Set refinement_applied=true
5. The loop will continue and re-validate

## CASE 3: Score < 90
⚠️ DO NOT CALL EXIT_LOOP IN THIS CASE
1. Read each issue in validation_result.issues
2. Apply suggestions from validation_result.suggestions
3. Preserve what was good (high INVEST scores)
4. Fix what was flagged (low INVEST scores)

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

# OUTPUT FORMAT
You MUST output valid JSON with this exact structure:
```json
{
  "refined_story": {
    "feature_id": <int>,
    "feature_title": "<string>",
    "title": "<string>",
    "description": "<string>",
    "acceptance_criteria": "<string with \\n separators>",
    "story_points": <int or null>
  },
  "is_valid": <boolean>,
  "refinement_applied": <boolean>,
  "refinement_notes": "<what was changed or 'No changes needed'>"
}
```

# IMPORTANT
- Call `exit_loop` ONLY when score >= 90 AND suggestions list is empty
- If suggestions exist (even at score 90+), apply them WITHOUT calling exit_loop
- `is_valid` should be true when validation passed or when you're confident your refinements fixed all issues
- If validation passed with no suggestions, set is_valid=true and refinement_applied=false
- If you applied suggestions (any score), set is_valid=true and refinement_applied=true

# EXAMPLE OUTPUT (Story was valid - called exit_loop first)
```json
{
  "refined_story": {
    "feature_id": 13,
    "feature_title": "Library of practical coding challenges",
    "title": "Browse coding challenge library",
    "description": "As a junior frontend developer, I want to browse coding challenges so that I can find practice problems.",
    "acceptance_criteria": "- User can view list of challenges\\n- Challenges show difficulty level\\n- User can filter by skill",
    "story_points": 3
  },
  "is_valid": true,
  "refinement_applied": false,
  "refinement_notes": "No changes needed - story passed validation with score 92."
}
```

# EXAMPLE OUTPUT (Story was refined)
```json
{
  "refined_story": {
    "feature_id": 13,
    "feature_title": "Library of practical coding challenges",
    "title": "Browse coding challenge library",
    "description": "As a junior frontend developer preparing for interviews, I want to browse a library of coding challenges so that I can find practice problems matched to my current skill level.",
    "acceptance_criteria": "- User can view a paginated list of coding challenges\\n- Each challenge displays title, difficulty (easy/medium/hard), and estimated time\\n- User can filter challenges by skill area (HTML, CSS, JavaScript)\\n- Empty state shows helpful message when no challenges match filters\\n- User can click a challenge to view its details",
    "story_points": 3
  },
  "is_valid": true,
  "refinement_applied": true,
  "refinement_notes": "Added specific persona, expanded benefit clause, added 2 more acceptance criteria including edge case for empty results."
}
```

Output ONLY the JSON object. No explanations, no markdown code fences.
"""

# --- Agent Definition ---
story_refiner_agent = LlmAgent(
    name="StoryRefinerAgent",
    model=model,
    instruction=STORY_REFINER_INSTRUCTION,
    description="Refines a user story based on validation feedback. Calls exit_loop when story is valid.",
    tools=[exit_loop],  # Provide the exit_loop tool for early termination
    output_key="refinement_result",  # Stores output in state['refinement_result']
)
