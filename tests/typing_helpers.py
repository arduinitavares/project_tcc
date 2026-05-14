"""Typing helpers for test doubles and persisted SQLModel rows."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from google.adk.tools import ToolContext


def require_id(value: int | None, name: str = "id") -> int:
    """Return a persisted SQLModel id, failing the test if it was not flushed."""
    if value is None:
        msg = f"{name} must be persisted"
        raise AssertionError(msg)
    return value


def make_tool_context(state: dict[str, object] | None = None) -> ToolContext:
    """Build a minimal ToolContext-compatible test double."""
    return cast("ToolContext", SimpleNamespace(state={} if state is None else state))
