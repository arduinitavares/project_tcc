"""Shared engine-resolution helper for spec services."""

from __future__ import annotations

from typing import Any, Callable


def resolve_spec_engine(
    *,
    service_get_engine: Callable[[], Any],
    default_service_get_engine: Callable[[], Any],
) -> Any:
    """Resolve the active engine while preserving spec-tools seams.

    Resolution order:
    1. An explicit ``tools.spec_tools.get_engine`` override.
    2. An explicit service-local ``get_engine`` monkeypatch.
    3. ``tools.spec_tools.engine`` when ``get_engine`` is still on the default path.
    4. The live ``models.db.get_engine`` binding.
    """

    from models import db as model_db

    try:
        from tools import spec_tools  # pylint: disable=import-outside-toplevel
    except ImportError:
        spec_tools = None

    live_get_engine = model_db.get_engine

    if spec_tools is not None:
        tool_get_engine = getattr(spec_tools, "get_engine", None)
        overridden_engine = getattr(spec_tools, "engine", None)
        default_tool_getters = {default_service_get_engine, live_get_engine}

        if callable(tool_get_engine) and tool_get_engine not in default_tool_getters:
            return tool_get_engine()

    if service_get_engine is not default_service_get_engine:
        return service_get_engine()

    if spec_tools is not None:
        tool_get_engine = getattr(spec_tools, "get_engine", None)
        overridden_engine = getattr(spec_tools, "engine", None)
        default_tool_getters = {default_service_get_engine, live_get_engine}

        if (
            overridden_engine is not None
            and overridden_engine is not model_db.engine
            and tool_get_engine in default_tool_getters
        ):
            return overridden_engine

    return live_get_engine()
