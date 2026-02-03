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
# Story query tools (extracted from legacy product_user_story_tool)
from tools.story_query_tools import query_features_for_stories
# Story Pipeline with LoopAgent + SequentialAgent (INVEST validation)
from orchestrator_agent.agent_tools.story_pipeline import (
    story_validation_loop,
)
from orchestrator_agent.agent_tools.story_pipeline.tools import (
    process_single_story,
    save_validated_stories,
)
# NEW: Sprint Planning tools (Scrum Master MVP)
from orchestrator_agent.agent_tools.sprint_planning.tools import (
    get_backlog_for_planning,
    plan_sprint_tool,
    save_sprint_tool,
)
from orchestrator_agent.agent_tools.sprint_planning.sprint_query_tools import (
    get_sprint_details,
    list_sprints,
)
from orchestrator_agent.agent_tools.sprint_planning.sprint_execution_tools import (
    update_story_status,
    batch_update_story_status,
    modify_sprint_stories,
    complete_sprint,
    complete_story_with_notes,
    update_acceptance_criteria,
    create_follow_up_story,
)
from tools.orchestrator_tools import (
    count_projects,
    get_project_by_name,
    get_project_details,
    list_projects,
    select_project,
    load_specification_from_file,
)
from tools.spec_tools import (
    save_project_specification,
    read_project_specification,
    compile_spec_authority_for_version,
    update_spec_and_compile_authority,
    ensure_accepted_spec_authority,
)
from tools.db_tools import (
    get_story_details,
)
from utils.helper import load_instruction
from utils.schemes import InputSchema
from utils.model_config import (
    get_model_id,
    get_openrouter_extra_body,
    get_story_pipeline_mode,
)

# --- Load environment and instruction ---
dotenv.load_dotenv()
INSTRUCTIONS_PATH = Path("orchestrator_agent/instructions.txt")
instruction_text = load_instruction(INSTRUCTIONS_PATH)
story_pipeline_mode = get_story_pipeline_mode()
instruction_text += (
    "\n\n[CONFIG] Story pipeline mode: "
    f"{story_pipeline_mode}. "
    "If mode is 'single', call process_single_story once per feature. "
    "If mode is 'batch', still call process_single_story per feature (no batch tool)."
)


# --- Initialize model ---
model = LiteLlm(
    model=get_model_id("orchestrator"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,  # Prevent passing unsupported params that trigger logging
    extra_body=get_openrouter_extra_body(),
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
        load_specification_from_file,
        # Specification tools
        save_project_specification,
        read_project_specification,
        compile_spec_authority_for_version,
        update_spec_and_compile_authority,
        ensure_accepted_spec_authority,
        # Story query tools
        get_story_details,
        query_features_for_stories,
        # Vision tools
        save_vision_tool,
        # Roadmap tools
        save_roadmap_tool,
        # Story Pipeline tools (INVEST-validated)
        process_single_story,
        save_validated_stories,  # Save without re-running pipeline
        # Sprint Planning tools (Scrum Master MVP)
        get_backlog_for_planning,
        plan_sprint_tool,
        save_sprint_tool,
        get_sprint_details,
        list_sprints,
        # Sprint Execution tools
        update_story_status,
        batch_update_story_status,
        modify_sprint_stories,
        complete_sprint,
        complete_story_with_notes,
        update_acceptance_criteria,
        create_follow_up_story,
        # Agent tools
        AgentTool(agent=vision_agent),
        AgentTool(agent=roadmap_agent),
        # Story validation pipeline (replaces legacy user_story_agent)
        AgentTool(agent=story_validation_loop),
    ],
    input_schema=InputSchema,
    instruction=instruction_text,
    output_key="orchestrator_response",
)
