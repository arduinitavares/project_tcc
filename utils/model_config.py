"""Model configuration loader for ADK agents."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml


_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "models.yaml"

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


@lru_cache(maxsize=1)
def _load_config() -> Dict[str, Any]:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"Model config not found: {_CONFIG_PATH}")
    raw = _CONFIG_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("Model config must be a YAML mapping")
    return data


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


def get_openrouter_extra_body() -> Dict[str, Any]:
    """Return extra_body for OpenRouter requests with strict privacy routing."""
    return {"provider": dict(OPENROUTER_PROVIDER)}


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
