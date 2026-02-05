"""Roadmap Builder Agent."""

import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body
from .schemes import RoadmapBuilderInput, RoadmapBuilderOutput

# Load instruction text
INSTRUCTIONS_PATH: Path = Path(__file__).parent / "instructions.txt"
ROADMAP_INSTRUCTIONS = load_instruction(INSTRUCTIONS_PATH)

# Load environment variables
dotenv.load_dotenv()

# Initialize Model
model: LiteLlm = LiteLlm(
    model=get_model_id("roadmap_builder"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)

# Initialize Agent
root_agent: Agent = Agent(
    name="roadmap_builder_tool",
    description="Constructs a roadmap from the prioritized backlog and context.",
    model=model,
    input_schema=RoadmapBuilderInput,
    output_schema=RoadmapBuilderOutput,
    output_key="roadmap_result",
    instruction=ROADMAP_INSTRUCTIONS,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
