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

from orchestrator_agent.agent_tools.product_vision_tool.tools import (
    get_current_time_tool,
    read_vision_tool,
)
from utils.helper import load_instruction
from utils.schemes import InputSchema, OutputSchema

# --- Load Instruction ---
INSTRUCTIONS_PATH: Path = Path(
    "orchestrator_agent/agent_tools/product_vision_tool/instructions.txt"
)
instructions = load_instruction(INSTRUCTIONS_PATH)

# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model ---
model: LiteLlm = LiteLlm(
    model="openrouter/openai/gpt-5.1", api_key=os.getenv("OPEN_ROUTER_API_KEY")
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
    tools=[read_vision_tool, get_current_time_tool],
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
