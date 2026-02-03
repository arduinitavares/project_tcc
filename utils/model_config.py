"""Model configuration loader for ADK agents."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any, Dict

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "models.yaml"

OPENROUTER_PROVIDER: Dict[str, Any] = {
    "data_collection": "deny",
    "zdr": True,
    "sort": "price",
    "allow_fallbacks": False,
    "require_parameters": True,
}

OPENROUTER_PRIVACY_ERROR_MESSAGE = (
    "No ZDR/data_collection=deny provider available for this model"
)

# ZDR retry configuration
ZDR_MAX_RETRIES = 5
ZDR_MAX_BACKOFF_SECONDS = 10.0


def is_zdr_routing_error(exception: BaseException) -> bool:
    """Check if an exception is a ZDR/privacy routing failure.
    
    These are transient errors when no privacy-compliant provider is available.
    They can be retried after a short delay.
    """
    message = str(exception).lower()
    return (
        "zdr" in message
        or "data_collection" in message
        or ("provider" in message and "no" in message)
        or "no providers" in message
    )


def _get_config_path() -> Path:
    env_path = os.getenv("MODEL_CONFIG_PATH")
    if not env_path:
        return _DEFAULT_CONFIG_PATH

    candidate = Path(env_path)
    if not candidate.is_absolute():
        candidate = (_REPO_ROOT / candidate).resolve()
    return candidate


@lru_cache(maxsize=1)
def _load_config() -> Dict[str, Any]:
    config_path = _get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Model config not found: {config_path}")
    raw = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("Model config must be a YAML mapping")
    return data


def clear_config_cache() -> None:
    """Clear cached model configuration (useful for tests)."""
    _load_config.cache_clear()


def get_model_id(key: str) -> str:
    """Get model identifier by key.

    Args:
        key: Model key under models.

    Returns:
        Model identifier string.
    """
    data = _load_config()
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise ValueError("models must be a mapping in models.yaml")
    model_id = models.get(key)
    if not model_id:
        raise KeyError(f"Model key not found in models.yaml: {key}")
    return str(model_id)


def _get_provider_config() -> Dict[str, Any]:
    relax_privacy = os.getenv("RELAX_ZDR_FOR_TESTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not relax_privacy:
        return dict(OPENROUTER_PROVIDER)

    relaxed_provider = dict(OPENROUTER_PROVIDER)
    relaxed_provider.update(
        {
            "data_collection": "allow",
            "zdr": False,
            "allow_fallbacks": True,
            "require_parameters": False,
        }
    )
    return relaxed_provider


def get_openrouter_extra_body() -> Dict[str, Any]:
    """Return extra_body for OpenRouter requests with privacy routing."""
    return {"provider": _get_provider_config()}


def get_story_pipeline_mode() -> str:
    """Return story pipeline mode from config.

    Allowed values: "batch" or "single".
    Defaults to "batch" when not configured.
    """
    data = _load_config()
    pipeline = data.get("story_pipeline", {})
    if pipeline is None:
        pipeline = {}
    if not isinstance(pipeline, dict):
        raise ValueError("story_pipeline must be a mapping in models.yaml")

    mode = str(pipeline.get("mode", "batch")).strip().lower()
    if mode not in {"batch", "single"}:
        raise ValueError("story_pipeline.mode must be 'batch' or 'single'")
    return mode


def get_story_pipeline_negation_tolerance() -> bool:
    """Return whether LLM negation tolerance is enabled for alignment checks."""
    data = _load_config()
    pipeline = data.get("story_pipeline", {})
    if pipeline is None:
        pipeline = {}
    if not isinstance(pipeline, dict):
        raise ValueError("story_pipeline must be a mapping in models.yaml")

    enabled = pipeline.get("negation_tolerance_llm", False)
    return bool(enabled)
