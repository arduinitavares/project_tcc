# orchestrator_agent/agent_tools/story_pipeline/invest_validator_agent/agent.py
"""
InvestValidatorAgent - Validates a user story against INVEST principles.

This agent receives a story draft and validates it, providing:
- is_valid: boolean
- validation_score: 0-100
- issues: list of specific problems found
- suggestions: actionable feedback for refinement

Output is stored in state['validation_result'] for the next agent.
"""

import os

import dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# --- Load Environment ---
dotenv.load_dotenv()

# --- Model ---
model = LiteLlm(
    model="openrouter/openai/gpt-4.1-mini",  # Fast validation
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)

# --- Instructions ---
INVEST_VALIDATOR_INSTRUCTION = """You are an expert Agile coach and user story quality reviewer.

# YOUR TASK
Validate the provided user story against INVEST principles and quality standards.

# INPUT (from state)
- `story_draft`: JSON object with the story to validate (title, description, acceptance_criteria, etc.)
- `current_feature`: The feature this story belongs to
- `product_context`: Product information for context

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

# OUTPUT FORMAT
You MUST output valid JSON with this exact structure:
```json
{
  "is_valid": <boolean>,
  "validation_score": <0-100>,
  "invest_scores": {
    "independent": <0-20>,
    "negotiable": <0-20>,
    "valuable": <0-20>,
    "estimable": <0-20>,
    "small": <0-20>,
    "testable": <0-20>
  },
  "issues": [
    "<specific issue 1>",
    "<specific issue 2>"
  ],
  "suggestions": [
    "<actionable suggestion 1>",
    "<actionable suggestion 2>"
  ],
  "verdict": "<brief summary of validation result>"
}
```

# VALIDATION THRESHOLDS
- is_valid = TRUE if validation_score >= 70 AND no critical issues
- Critical issues: missing acceptance criteria, no user value, story too large

# EXAMPLE OUTPUT (Valid)
```json
{
  "is_valid": true,
  "validation_score": 85,
  "invest_scores": {
    "independent": 20,
    "negotiable": 15,
    "valuable": 20,
    "estimable": 15,
    "small": 15,
    "testable": 20
  },
  "issues": [],
  "suggestions": [
    "Consider adding an edge case for empty search results"
  ],
  "verdict": "Story meets INVEST criteria. Minor improvement possible but acceptable as-is."
}
```

# EXAMPLE OUTPUT (Invalid)
```json
{
  "is_valid": false,
  "validation_score": 45,
  "invest_scores": {
    "independent": 10,
    "negotiable": 10,
    "valuable": 15,
    "estimable": 5,
    "small": 5,
    "testable": 0
  },
  "issues": [
    "No acceptance criteria provided",
    "Story is too large - covers multiple features",
    "Description missing 'so that' benefit clause"
  ],
  "suggestions": [
    "Add 3-5 specific, testable acceptance criteria",
    "Split into smaller stories: one for browsing, one for filtering",
    "Complete the description: 'so that I can find relevant challenges quickly'"
  ],
  "verdict": "Story needs significant rework. Missing acceptance criteria is a critical issue."
}
```

Output ONLY the JSON object. No explanations, no markdown code fences.
"""

# --- Agent Definition ---
invest_validator_agent = LlmAgent(
    name="InvestValidatorAgent",
    model=model,
    instruction=INVEST_VALIDATOR_INSTRUCTION,
    description="Validates a user story against INVEST principles.",
    output_key="validation_result",  # Stores output in state['validation_result']
)
