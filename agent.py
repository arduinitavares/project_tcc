# agent.py
"""This is the orchestrator agent module."""


import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import DatabaseSessionService

from utils.helper import load_instruction
from utils.schemes import InputSchema, OutputSchema

# --- Load Instruction ---
INSTRUCTIONS_PATH: Path = Path("orchestrator_instructions.txt")
instructions = load_instruction(INSTRUCTIONS_PATH)

# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model ---
model: LiteLlm = LiteLlm(
    model="openrouter/openai/gpt-5-nano", api_key=os.getenv("OPEN_ROUTER_API_KEY")
)


# --- Initialize Persistent Session Service ---
# Using SQLite database for persistent storage
DB_URL = "sqlite:///projects_data.db"
session_service = DatabaseSessionService(db_url=DB_URL)

# --- Create Agent ---
root_agent: Agent = Agent(
    name="Orchestrator Agent",
    description=(
        "An orchestrator agent that manages the workflow between "
        "the product vision agent and the product roadmap agent."
    ),
    model=model,
    input_schema=InputSchema,
    instruction=instructions,
    output_key="product_vision_assessment",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
