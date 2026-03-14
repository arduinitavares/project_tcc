"""Runtime setup for spec validator agent dependencies."""

from google.adk.models.lite_llm import LiteLlm

from utils.model_config import get_model_id, get_openrouter_extra_body
from utils.runtime_config import get_openrouter_api_key, get_spec_validator_max_tokens

_DEFAULT_MAX_TOKENS = 4096
_spec_validator_max_tokens = get_spec_validator_max_tokens(_DEFAULT_MAX_TOKENS)

model = LiteLlm(
    model=get_model_id("spec_validator"),
    api_key=get_openrouter_api_key(),
    drop_params=True,
    extra_body=get_openrouter_extra_body(),
    max_tokens=_spec_validator_max_tokens,
)
