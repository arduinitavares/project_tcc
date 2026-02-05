# orchestrator_agent\agent_tools\backlog_primer\agent.py

"""
backlog_primer_agent.py

Defines a Google ADK agent that builds an initial high-level product backlog.
"""

import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body

from .schemes import InputSchema, OutputSchema


INSTRUCTIONS_PATH: Path = Path(__file__).parent / "instructions.txt"
BACKLOG_INSTRUCTIONS = load_instruction(INSTRUCTIONS_PATH)

dotenv.load_dotenv()

model: LiteLlm = LiteLlm(
    model=get_model_id("backlog_primer"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)

root_agent: Agent = Agent(
    name="backlog_primer_tool",
    description=(
        "An agent that produces an initial high-level product backlog "
        "from a product vision and user input."
    ),
    model=model,
    input_schema=InputSchema,
    output_schema=OutputSchema,
    output_key="product_backlog",
    instruction=BACKLOG_INSTRUCTIONS,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
