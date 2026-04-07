"""Incremental models package boundary."""

from __future__ import annotations

from importlib import import_module


__all__ = ["core", "db", "enums", "events", "specs"]


def __getattr__(name: str):
    """Lazily expose subpackages without importing db on every package import."""
    if name in __all__:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
