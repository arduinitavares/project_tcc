"""Helpers for intentional command-line script output."""

from __future__ import annotations

from builtins import print as _print
from typing import TextIO


def emit(
    *values: object,
    sep: str = " ",
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    """Write user-facing script output."""
    _print(*values, sep=sep, end=end, file=file, flush=flush)
