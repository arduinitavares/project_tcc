"""
product_vision_agent.py

This script defines and runs a Google ADK agent that generates a
product vision statement. If information is missing, it returns a
draft and clarifying questions.
"""

import os
from pathlib import Path
from typing import Annotated

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from pydantic import BaseModel, Field
from utils.helper import load_instruction

# --- Load Instruction ---
INSTRUCTIONS_PATH: Path = Path("product_vision_agent/instructions.txt")
instructions = load_instruction(INSTRUCTIONS_PATH)

# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model ---
model: LiteLlm = LiteLlm(
    model="openrouter/openai/gpt-5-nano", api_key=os.getenv("OPEN_ROUTER_API_KEY")
)


# --- Define Schemas ---
class InputSchema(BaseModel):
    """Schema for the input unstructured requirements text."""

    unstructured_requirements: Annotated[
        str,
        Field(
            description=(
                "Raw, unstructured text containing product requirements and " "ideas."
            ),
        ),
    ]


class OutputSchema(BaseModel):
    """
    Schema for the output, which can be a final vision or a
    draft with questions.
    """

    product_vision_statement: Annotated[
        str,
        Field(
            description=(
                "The product vision statement. This will be a final, "
                "complete statement OR a draft with placeholders "
                "(e.g., '[Missing Target User]') if info is missing."
            ),
        ),
    ]

    is_complete: Annotated[
        bool,
        Field(
            description=(
                "True if the vision statement is final and complete. "
                "False if it is a draft and requires more information."
            ),
        ),
    ]

    clarifying_questions: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "A list of specific questions for the user to answer "
                "to fill in the missing parts of the vision. "
                "This list will be empty if 'is_complete' is True."
            ),
        ),
    ]


# --- Create Agent ---
product_vision_agent: Agent = Agent(
    name="product_vision_agent",
    description=(
        "An agent that creates a product vision from unstructured "
        "requirements. Asks questions if info is missing."
    ),
    model=model,
    input_schema=InputSchema,
    output_schema=OutputSchema,
    instruction=instructions,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
