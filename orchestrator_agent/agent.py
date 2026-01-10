# agent.py
"""Orchestrator agent definition."""

import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

from orchestrator_agent.agent_tools.product_roadmap_agent.agent import (
    root_agent as roadmap_agent,
)
from orchestrator_agent.agent_tools.product_roadmap_agent.tools import (
    save_roadmap_tool,
)
from orchestrator_agent.agent_tools.product_vision_tool.agent import (
    root_agent as vision_agent,
)
from orchestrator_agent.agent_tools.product_vision_tool.tools import (
    save_vision_tool,
)
# Legacy user story tool (kept for backward compatibility)
from orchestrator_agent.agent_tools.product_user_story_tool.agent import (
    root_agent as user_story_agent,
)
from orchestrator_agent.agent_tools.product_user_story_tool.tools import (
    create_user_story_tool,
    batch_create_user_stories_tool,
    query_features_for_stories,
)
# NEW: Story Pipeline with LoopAgent + SequentialAgent (INVEST validation)
from orchestrator_agent.agent_tools.story_pipeline import (
    story_validation_loop,
)
from orchestrator_agent.agent_tools.story_pipeline.tools import (
    process_single_story,
    process_story_batch,
    save_validated_stories,
)
from tools.orchestrator_tools import (
    count_projects,
    get_project_by_name,
    get_project_details,
    list_projects,
    select_project,
)
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
        # Project management tools
        count_projects,
        list_projects,
        get_project_details,
        get_project_by_name,
        select_project,
        # Vision tools
        save_vision_tool,
        # Roadmap tools
        save_roadmap_tool,
        # Story query tools
        query_features_for_stories,
        # NEW: Story Pipeline tools (INVEST-validated)
        process_single_story,
        process_story_batch,
        save_validated_stories,  # Save without re-running pipeline
        # Legacy story tools (for backward compatibility)
        create_user_story_tool,
        batch_create_user_stories_tool,
        # Agent tools
        AgentTool(agent=vision_agent),
        AgentTool(agent=roadmap_agent),
        AgentTool(agent=user_story_agent),
        # NEW: Story validation pipeline
        AgentTool(agent=story_validation_loop),
    ],
    input_schema=InputSchema,
    instruction=instruction_text,
    output_key="orchestrator_response",
)
