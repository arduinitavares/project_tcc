"""Shared engine-resolution helper for spec services."""

from __future__ import annotations

import importlib
from contextlib import suppress
from typing import TYPE_CHECKING

from models import db as model_db

if TYPE_CHECKING:
    from collections.abc import Callable


def _resolve_spec_tools_module() -> object | None:
    """Load the legacy spec-tools module when available."""
    spec_tools_module: object | None = None
    with suppress(ImportError):
        spec_tools_module = importlib.import_module("tools.spec_tools")
    return spec_tools_module


def resolve_spec_engine(
    *,
    service_get_engine: Callable[[], object],
    default_service_get_engine: Callable[[], object],
) -> object:
    """Resolve the active engine while preserving spec-tools seams.

    Resolution order:
    1. An explicit ``tools.spec_tools.get_engine`` override.
    2. An explicit service-local ``get_engine`` monkeypatch.
    3. ``tools.spec_tools.engine`` when ``get_engine`` is still on the default path.
    4. The live ``models.db.get_engine`` binding.
    """
    spec_tools_module = _resolve_spec_tools_module()
    live_get_engine = model_db.get_engine

    if spec_tools_module is not None:
        tool_get_engine = getattr(spec_tools_module, "get_engine", None)
        default_tool_getters = {default_service_get_engine, live_get_engine}

        if callable(tool_get_engine) and tool_get_engine not in default_tool_getters:
            return tool_get_engine()

    if service_get_engine is not default_service_get_engine:
        return service_get_engine()

    if spec_tools_module is not None:
        tool_get_engine = getattr(spec_tools_module, "get_engine", None)
        overridden_engine = getattr(spec_tools_module, "engine", None)
        default_tool_getters = {default_service_get_engine, live_get_engine}

        if (
            overridden_engine is not None
            and overridden_engine is not model_db.engine
            and tool_get_engine in default_tool_getters
        ):
            return overridden_engine

    return live_get_engine()
