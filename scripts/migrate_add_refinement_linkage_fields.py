#!/usr/bin/env python3
"""Add deterministic backlog/refinement linkage columns to user_stories."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from db.migrations import migrate_performance_indexes, migrate_user_story_refinement_linkage
from agile_sqlmodel import get_engine


def main() -> None:
    engine = get_engine()
    actions = []
    actions.extend(migrate_user_story_refinement_linkage(engine))
    actions.extend(migrate_performance_indexes(engine))

    if actions:
        print("Applied migrations:")
        for action in actions:
            print(f"- {action}")
    else:
        print("No migrations needed (schema already current).")


if __name__ == "__main__":
    main()
