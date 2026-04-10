"""This module contains utility functions for the product vision agent."""

from pathlib import Path


def load_instruction(path: Path) -> str:
    """Load instruction text from a file."""
    with path.open(encoding="utf-8") as file:
        return file.read()
