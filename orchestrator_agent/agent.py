# agent.py
"""Orchestrator agent definition."""

import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

# from product_roadmap_agent.agent import root_agent as roadmap_agent
from orchestrator_agent.agent_tools.product_vision_tool.agent import (
    root_agent as vision_agent,
)
from orchestrator_agent.agent_tools.product_vision_tool.tools import (
    save_vision_tool,
)
from tools.orchestrator_tools import count_projects, list_projects
from utils.helper import load_instruction
from utils.schemes import InputSchema

# --- Load environment and instruction ---
dotenv.load_dotenv()
INSTRUCTIONS_PATH = Path("orchestrator_agent/instructions.txt")
instruction_text = load_instruction(INSTRUCTIONS_PATH)


# --- Initialize model ---
model = LiteLlm(
    model="openrouter/google/gemini-2.5-pro",
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,  # Prevent passing unsupported params that trigger logging
)

# --- Define the agent ---
root_agent = Agent(
    name="orchestrator_agent",  # must match folder name, no spaces
    description="Routing agent for the Agile platform.",
    model=model,
    tools=[
        count_projects,
        list_projects,
        save_vision_tool,
        AgentTool(agent=vision_agent),
        # AgentTool(agent=roadmap_agent),
    ],
    input_schema=InputSchema,
    instruction=instruction_text,
    output_key="orchestrator_response",
)
