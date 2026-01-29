"""Model configuration loader for ADK agents."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml


_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


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
