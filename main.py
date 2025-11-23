# main.py
"""Start ADK Web with in-memory session management."""

from __future__ import annotations

import subprocess


def start_adk_web() -> None:
    """Start ADK Web with in-memory session service (no persistence)."""
    subprocess.run(
        [
            "adk",
            "web",
            ".",
        ],
        check=True,
    )


def main() -> None:
    """Launch ADK Web."""
    print("Starting ADK Web with in-memory sessions...")
    start_adk_web()


if __name__ == "__main__":
    main()
