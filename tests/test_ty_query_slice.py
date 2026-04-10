"""Regression coverage for the current high-signal ty cleanup slice."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_ty_query_slice_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()

    result = subprocess.run(
        [
            "uv",
            "run",
            "ty",
            "check",
            "tools/story_query_tools.py",
            "tools/db_tools.py",
            "repositories/story.py",
            "services/orchestrator_context_service.py",
            "--output-format",
            "concise",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
