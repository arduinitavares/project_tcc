"""Runtime setup for spec validator agent dependencies."""

import os

import dotenv
from google.adk.models.lite_llm import LiteLlm

from utils.model_config import get_model_id, get_openrouter_extra_body

dotenv.load_dotenv()

_DEFAULT_MAX_TOKENS = 4096
_spec_validator_max_tokens = int(
    os.getenv("SPEC_VALIDATOR_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))
)

model = LiteLlm(
    model=get_model_id("spec_validator"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
    max_tokens=_spec_validator_max_tokens,
)
