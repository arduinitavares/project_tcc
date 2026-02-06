"""
Sprint Planner agent definition.
"""

import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body

from .schemes import SprintPlannerInput, SprintPlannerOutput


INSTRUCTIONS_PATH: Path = Path(__file__).parent / "instructions.txt"
SPRINT_PLANNER_INSTRUCTIONS = load_instruction(INSTRUCTIONS_PATH)

dotenv.load_dotenv()

model: LiteLlm = LiteLlm(
    model=get_model_id("sprint_planner"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)

root_agent: Agent = Agent(
    name="sprint_planner_tool",
    description=(
        "An agent that converts a prioritized product backlog into a committed "
        "sprint backlog with sprint goal, capacity reasoning, and tasks."
    ),
    model=model,
    input_schema=SprintPlannerInput,
    output_schema=SprintPlannerOutput,
    output_key="sprint_plan",
    instruction=SPRINT_PLANNER_INSTRUCTIONS,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
