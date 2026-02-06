"""User Story Writer Agent."""

import os
from pathlib import Path

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body
from .schemes import UserStoryWriterInput, UserStoryWriterOutput

# Load instruction text
INSTRUCTIONS_PATH: Path = Path(__file__).parent / "instructions.txt"
USER_STORY_WRITER_INSTRUCTIONS = load_instruction(INSTRUCTIONS_PATH)

# Load environment variables
dotenv.load_dotenv()


def create_user_story_writer_agent() -> Agent:
    """Factory: create a fresh User Story Writer agent instance."""
    model: LiteLlm = LiteLlm(
        model=get_model_id("user_story_writer"),
        api_key=os.getenv("OPEN_ROUTER_API_KEY"),
        drop_params=True,
        extra_body=get_openrouter_extra_body(),
    )
    return Agent(
        name="user_story_writer_tool",
        description=(
            "Decomposes a single high-level roadmap requirement into "
            "INVEST-compliant, Scrum user stories (Stage 2 → Chapter 5)."
        ),
        model=model,
        input_schema=UserStoryWriterInput,
        output_schema=UserStoryWriterOutput,
        output_key="story_writer_result",
        instruction=USER_STORY_WRITER_INSTRUCTIONS,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


# Module-level singleton (used by AgentTool wrapping)
root_agent: Agent = create_user_story_writer_agent()
