# orchestrator_agent/agent_tools/product_user_story_tool/agent.py
"""
product_user_story_agent.py

This agent generates INVEST-compliant user stories from roadmap features.
It operates statelessly, receiving context as JSON strings.
"""

import os
from pathlib import Path
from typing import Annotated, List, Optional

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from pydantic import BaseModel, Field


def load_instruction(path: Path) -> str:
    """Utility function to load instruction text from a file."""
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


# --- Load Instruction ---
print("Loading user story agent instructions...")
INSTRUCTIONS_PATH: Path = Path(
    "orchestrator_agent/agent_tools/product_user_story_tool/instructions.txt"
)
USER_STORY_INSTRUCTIONS = load_instruction(INSTRUCTIONS_PATH)
print("Instructions loaded.")

# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model ---
model: LiteLlm = LiteLlm(
    model="openrouter/openai/gpt-5.1",
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)


# --- Define Input Schema ---


class UserStoryInputSchema(BaseModel):
    """Schema for the input to the user story agent."""

    active_project_context: Annotated[
        str,
        Field(
            description=(
                "JSON string containing product_id and product_name. "
                "Example: '{\"product_id\": 10, \"product_name\": \"MealMuse\"}'"
            ),
        ),
    ]

    roadmap_context: Annotated[
        str,
        Field(
            description=(
                "JSON string listing available features with their IDs, "
                "organized by theme/epic. Pass 'NO_FEATURES' if no structure exists yet. "
                "Example: '[{\"feature_id\": 1, \"feature_title\": \"Manual ingredient entry\", "
                "\"theme\": \"Pantry Management\", \"epic\": \"Ingredient Input\"}]'"
            ),
        ),
    ]

    prior_stories_state: Annotated[
        str,
        Field(
            description=(
                "JSON string containing any previously generated stories in this session "
                "(for multi-turn story creation). Pass 'NO_HISTORY' for first call."
            ),
        ),
    ]

    user_input: Annotated[
        str,
        Field(
            description=(
                "The user's request or answers to clarifying questions. "
                "Examples: 'create user stories for the Now slice', "
                "'3 stories per feature', 'focus on Pantry Management theme'."
            ),
        ),
    ]


# --- Define Output Schema ---


class StoryDraft(BaseModel):
    """A single user story to be created."""

    feature_id: Annotated[
        int,
        Field(description="The ID of the feature this story belongs to."),
    ]
    feature_title: Annotated[
        str,
        Field(description="The title of the parent feature (for reference)."),
    ]
    title: Annotated[
        str,
        Field(
            description=(
                "Short, action-oriented title for the story. "
                "Example: 'Add ingredient to pantry'"
            ),
        ),
    ]
    description: Annotated[
        str,
        Field(
            description=(
                "The story in 'As a [user], I want [action] so that [benefit]' format."
            ),
        ),
    ]
    acceptance_criteria: Annotated[
        Optional[str],
        Field(
            description=(
                "Bullet-point acceptance criteria (each starting with '- '). "
                "Example: '- User can type ingredient name\\n- Autocomplete suggests matches'"
            ),
        ),
    ]
    story_points: Annotated[
        Optional[int],
        Field(
            description=(
                "Optional story point estimate (1, 2, 3, 5, 8, 13). "
                "Return null unless user requested estimates."
            ),
        ),
    ]


class UserStoryOutputSchema(BaseModel):
    """Schema for the output from the user story agent."""

    stories_to_create: Annotated[
        List[StoryDraft],
        Field(
            description=(
                "List of user stories ready to be persisted. "
                "Empty if clarification is needed."
            ),
        ),
    ]

    is_complete: Annotated[
        bool,
        Field(
            description=(
                "True if stories are ready to create without ambiguity. "
                "False if clarifying questions need answers first."
            ),
        ),
    ]

    clarifying_questions: Annotated[
        List[str],
        Field(
            description=(
                "Questions for the user if scope is unclear. "
                "Empty if is_complete is true."
            ),
        ),
    ]

    summary: Annotated[
        str,
        Field(
            description=(
                "A brief summary of what was generated or what's needed. "
                "Example: 'Generated 6 stories for Pantry Management features' or "
                "'Need to know which features to focus on'."
            ),
        ),
    ]


# --- Create Agent ---
root_agent: Agent = Agent(
    name="product_user_story_tool",
    description=(
        "An agent that generates INVEST-compliant user stories from roadmap features. "
        "Takes feature context and user scope, returns stories with acceptance criteria."
    ),
    model=model,
    input_schema=UserStoryInputSchema,
    output_schema=UserStoryOutputSchema,
    output_key="user_stories_output",
    instruction=USER_STORY_INSTRUCTIONS,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
