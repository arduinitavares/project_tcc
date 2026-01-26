"""
Migration script to add product_personas table to existing database.
This preserves all existing data while adding the new table.
"""
import sys
from pathlib import Path

# Add parent directory to path to import agile_sqlmodel
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from agile_sqlmodel import DB_URL, ProductPersona, SQLModel

def migrate_add_product_personas():
    """Add product_personas table to existing database."""
    engine = create_engine(DB_URL, echo=True)
    
    # Check if table already exists
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='product_personas'"
        ))
        exists = result.fetchone() is not None
    
    if exists:
        print("✓ product_personas table already exists. No migration needed.")
        return
    
    print("Adding product_personas table to database...")
    
    # Create only the ProductPersona table
    ProductPersona.metadata.create_all(engine)
    
    print("✓ Migration complete! product_personas table added successfully.")
    print("\nYou can now seed personas for existing products using:")
    print("  from tools.db_tools import seed_product_personas")

if __name__ == "__main__":
    migrate_add_product_personas()
