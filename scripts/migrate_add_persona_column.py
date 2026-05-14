"""
Migration script to add persona column to user_stories table.

This preserves all existing data while adding the new column.
"""

import sys
from pathlib import Path

from utils.cli_output import emit

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text

from agile_sqlmodel import get_database_url


def migrate_add_persona_column() -> None:
    """Add persona column to user_stories table."""
    engine = create_engine(get_database_url(), echo=True)

    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("PRAGMA table_info(user_stories)"))
        columns = [row[1] for row in result.fetchall()]

        if "persona" in columns:
            emit(
                "✓ Column 'persona' already exists in user_stories table. No migration needed."  # noqa: E501
            )
            return

        emit("Adding 'persona' column to user_stories table...")

        # Add the column
        conn.execute(text("ALTER TABLE user_stories ADD COLUMN persona VARCHAR(100)"))

        # Create index for the new column
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_stories_persona ON user_stories (persona)"  # noqa: E501
            )
        )

        conn.commit()

        emit("✓ Migration complete! Column 'persona' added successfully.")
        emit("\nThe persona field will be auto-extracted from story descriptions.")


if __name__ == "__main__":
    migrate_add_persona_column()
