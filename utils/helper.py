"""This module contains utility functions for the product vision agent."""

from pathlib import Path


def load_instruction(path: Path) -> str:
    """Utility function to load instruction text from a file."""
    with open(path, "r", encoding="utf-8") as file:
        return file.read()
