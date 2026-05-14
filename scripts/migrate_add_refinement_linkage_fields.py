#!/usr/bin/env python3
"""Add deterministic backlog/refinement linkage columns to user_stories."""

import sys
from pathlib import Path

from utils.cli_output import emit

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from agile_sqlmodel import get_engine  # noqa: E402
from db.migrations import (  # noqa: E402
    migrate_performance_indexes,
    migrate_user_story_refinement_linkage,
)


def main() -> None:
    """Return main."""
    engine = get_engine()
    actions = []
    actions.extend(migrate_user_story_refinement_linkage(engine))
    actions.extend(migrate_performance_indexes(engine))

    if actions:
        emit("Applied migrations:")
        for action in actions:
            emit(f"- {action}")
    else:
        emit("No migrations needed (schema already current).")


if __name__ == "__main__":
    main()
