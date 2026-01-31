"""
product_roadmap_agent.py

This script defines and runs a Google ADK agent that helps a Product Owner
build a high-level product roadmap from a product vision.
"""

import os
from pathlib import Path
from typing import Annotated, Dict, List, Optional

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from pydantic import BaseModel, Field

from utils.model_config import get_model_id, get_openrouter_extra_body


def load_instruction(path: Path) -> str:
    """Utility function to load instruction text from a file."""
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


# --- Load Instruction ---
# We will define instructions inline here, but you can move to a .txt file
print("Loading roadmap agent instructions...")
INSTRUCTIONS_PATH: Path = Path(
    "orchestrator_agent/agent_tools/product_roadmap_agent/instructions.txt"
)
ROADMAP_INSTRUCTIONS = load_instruction(INSTRUCTIONS_PATH)
print("Instructions loaded.")
# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model ---
# We can reuse the same model and API key configuration
model: LiteLlm = LiteLlm(
    model=get_model_id("product_roadmap"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,  # Prevent passing unsupported params
    extra_body=get_openrouter_extra_body(),
)

# --- Define Tool Context ---

context: Dict[str, str] = {
    "product_vision_statement": "To be defined.",
    "Product_roadmap": "To be defined.",
    "unstructured_requirements": "To be defined.",
}

# --- Define Schemas ---


class InputSchema(BaseModel):
    """Schema for the input to the roadmap agent."""

    product_vision_statement: Annotated[
        str,
        Field(description="The final, approved product vision statement."),
    ]

    prior_roadmap_state: Annotated[
        str,
        Field(
            description=(
                "JSON string containing the previous roadmap_draft and any "
                "accumulated context from prior turns. Pass 'NO_HISTORY' "
                "for the very first call when starting fresh."
            ),
        ),
    ]

    user_input: Annotated[
        str,
        Field(
            description=(
                "Raw, unstructured text containing high-level requirements, "
                "epics, features, or answers to the agent's "
                "previous questions."
            ),
        ),
    ]


class RoadmapTheme(BaseModel):
    """
    Represents a single high-level theme or epic on the roadmap.
    """

    theme_name: Annotated[
        str,
        Field(
            description="The high-level name of the theme, e.g., 'User "
            "Authentication' or 'Task Prioritization AI'."
        ),
    ]

    key_features: Annotated[
        List[str],
        Field(
            description="A list of major features that fall under this " "theme.",
        ),
    ]

    justification: Annotated[
        Optional[str],
        Field(
            description="The 'why' behind this theme's priority, e.g., "
            "'Core to value prop' or 'High customer request'.",
        ),
    ]

    time_frame: Annotated[
        Optional[str],
        Field(
            description="The high-level, agile time frame, e.g., 'Now', "
            "'Next', or 'Later'.",
        ),
    ]


class OutputSchema(BaseModel):
    """
    Schema for the output, which is a draft of the roadmap
    and any clarifying questions.
    """

    roadmap_draft: Annotated[
        List[RoadmapTheme],
        Field(
            description=(
                "The current draft of the product roadmap, grouped into themes."
            ),
        ),
    ]

    is_complete: Annotated[
        bool,
        Field(
            description=(
                "True if the roadmap draft is complete and confirmed. "
                "False if it is still in progress and requires more input."
            ),
        ),
    ]

    clarifying_questions: Annotated[
        list[str],
        Field(
            description=(
                "A list of specific questions for the user to answer "
                "to move to the next step of the roadmap process."
            ),
        ),
    ]


# --- Create Agent ---
root_agent: Agent = Agent(
    name="product_roadmap_tool",
    description=(
        "An agent that guides a user to create a high-level agile product "
        "roadmap, starting from a product vision."
    ),
    model=model,
    input_schema=InputSchema,
    output_schema=OutputSchema,
    output_key="product_roadmap",
    instruction=ROADMAP_INSTRUCTIONS,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
