"""
NegationCheckerAgent - Determines whether a forbidden capability mention is negated.

Input: NegationCheckInput (JSON string)
Output: NegationCheckOutput (JSON only)
"""

import os
from pathlib import Path

import dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id, get_openrouter_extra_body
from utils.schemes import NegationCheckInput, NegationCheckOutput

# --- Load Environment ---
dotenv.load_dotenv()

# --- Model ---
model = LiteLlm(
    model=get_model_id("negation_checker"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
)


def create_negation_checker_agent() -> LlmAgent:
    """Create a new NegationCheckerAgent instance.

    Returns:
        LlmAgent: Fresh NegationCheckerAgent instance.
    """
    return LlmAgent(
        name="NegationCheckerAgent",
        model=model,
        instruction=load_instruction(Path(__file__).parent / "instructions.txt"),
        description="Determines whether a forbidden capability mention is negated.",
        input_schema=NegationCheckInput,
        output_key="negation_check_result",
        output_schema=NegationCheckOutput,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


negation_checker_agent = create_negation_checker_agent()
