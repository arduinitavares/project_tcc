"""
Migration script to add product_personas table to existing database.

This preserves all existing data while adding the new table.
"""

import sys
from pathlib import Path

from utils.cli_output import emit

# Add parent directory to path to import agile_sqlmodel
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text

from agile_sqlmodel import get_database_url
from models.core import ProductPersona


def migrate_add_product_personas() -> None:
    """Add product_personas table to existing database."""
    engine = create_engine(get_database_url(), echo=True)

    # Check if table already exists
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='product_personas'"  # noqa: E501
            )
        )
        exists = result.fetchone() is not None

    if exists:
        emit("✓ product_personas table already exists. No migration needed.")
        return

    emit("Adding product_personas table to database...")

    # Create only the ProductPersona table
    ProductPersona.metadata.create_all(engine)

    emit("✓ Migration complete! product_personas table added successfully.")
    emit("\nYou can now seed personas for existing products using:")
    emit("  from tools.db_tools import seed_product_personas")


if __name__ == "__main__":
    migrate_add_product_personas()
