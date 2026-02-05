"""
product_vision_agent.py

This script defines and runs a Google ADK agent that generates a
product vision statement. If information is missing, it returns a
draft and clarifying questions.
"""

import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from .schemes import InputSchema, OutputSchema
from utils.model_config import get_model_id, get_openrouter_extra_body

# --- Load Instruction ---
INSTRUCTIONS_PATH: Path = Path(
    "orchestrator_agent/agent_tools/product_vision_tool/instructions.txt"
)
instructions = load_instruction(INSTRUCTIONS_PATH)

# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model with drop_params to prevent logging issues ---
model: LiteLlm = LiteLlm(
    model=get_model_id("product_vision"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,  # Prevent passing unsupported params that trigger logging
    extra_body=get_openrouter_extra_body(),
)


# --- Create Agent ---
root_agent: Agent = Agent(
    name="product_vision_tool",
    description=(
        "An agent that creates a product vision from unstructured "
        "requirements. Asks questions if info is missing."
    ),
    model=model,
    input_schema=InputSchema,
    output_schema=OutputSchema,
    instruction=instructions,
    output_key="product_vision_assessment",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
