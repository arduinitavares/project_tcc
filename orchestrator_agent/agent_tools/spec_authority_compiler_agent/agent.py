"""spec_authority_compiler_agent - agent-first compiler for spec authority."""

import os

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from utils.schemes import SpecAuthorityCompilerInput, SpecAuthorityCompilerEnvelope
from utils.model_config import get_model_id, get_openrouter_extra_body
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.instructions_source import (
    SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
)

# --- Load Environment Variables ---
dotenv.load_dotenv()

# --- Initialize Model ---
model = LiteLlm(
    model=get_model_id("spec_authority_compiler"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)

# --- Create Agent ---
disable_schema = os.getenv("SPEC_COMPILER_DISABLE_SCHEMA") == "1"
output_schema = None if disable_schema else SpecAuthorityCompilerEnvelope

root_agent = Agent(
    name="spec_authority_compiler_agent",
    description="Compiler-style agent that extracts spec authority in strict JSON.",
    model=model,
    input_schema=SpecAuthorityCompilerInput,
    output_schema=output_schema,
    instruction=SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
    output_key="spec_authority_compilation",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
