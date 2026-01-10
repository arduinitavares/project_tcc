# orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/agent.py
"""
StoryDraftAgent - Generates a single INVEST-compliant user story from a feature.

This agent receives ONE feature at a time and generates ONE user story.
Output is stored in state['story_draft'] for the next agent in the pipeline.
"""

import os

import dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# --- Load Environment ---
dotenv.load_dotenv()

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
- `current_feature`: JSON object with feature_id, feature_title, theme, epic
- `product_context`: JSON with product_id, product_name, vision
- `user_persona`: The target user persona (e.g., "junior frontend developer")
- `story_preferences`: Any user preferences (story points yes/no, etc.)
- `refinement_feedback`: If this is a retry, contains feedback from validator (otherwise empty)

# OUTPUT FORMAT
You MUST output valid JSON with this exact structure:
```json
{
  "feature_id": <int>,
  "feature_title": "<string>",
  "title": "<short action-oriented title>",
  "description": "As a <persona>, I want <action> so that <benefit>.",
  "acceptance_criteria": "- Criterion 1\\n- Criterion 2\\n- Criterion 3\\n- Criterion 4",
  "story_points": <int or null>
}
```

# INVEST PRINCIPLES (follow strictly)
- **Independent**: Story can be developed without depending on other stories
- **Negotiable**: Details can be discussed, not a rigid contract
- **Valuable**: Delivers clear value to the user
- **Estimable**: Small enough to estimate accurately
- **Small**: Fits in a single sprint (1-8 story points)
- **Testable**: Acceptance criteria are verifiable

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

# EXAMPLE OUTPUT
```json
{
  "feature_id": 13,
  "feature_title": "Library of practical coding challenges",
  "title": "Browse coding challenge library",
  "description": "As a junior frontend developer preparing for interviews, I want to browse a library of coding challenges so that I can find practice problems matched to my skill level.",
  "acceptance_criteria": "- User can view a list of available coding challenges\\n- Each challenge displays title, difficulty level, and estimated time\\n- User can filter challenges by skill area (HTML, CSS, JS)\\n- User can sort challenges by difficulty or recency\\n- Clicking a challenge opens its detail view",
  "story_points": 3
}
```

Output ONLY the JSON object. No explanations, no markdown code fences.
"""

# --- Agent Definition ---
story_draft_agent = LlmAgent(
    name="StoryDraftAgent",
    model=model,
    instruction=STORY_DRAFT_INSTRUCTION,
    description="Generates a single user story draft from a feature.",
    output_key="story_draft",  # Stores output in state['story_draft']
)
