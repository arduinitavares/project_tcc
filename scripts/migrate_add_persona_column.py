"""
Migration script to add persona column to user_stories table.
This preserves all existing data while adding the new column.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from agile_sqlmodel import DB_URL

def migrate_add_persona_column():
    """Add persona column to user_stories table."""
    engine = create_engine(DB_URL, echo=True)
    
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("PRAGMA table_info(user_stories)"))
        columns = [row[1] for row in result.fetchall()]
        
        if "persona" in columns:
            print("✓ Column 'persona' already exists in user_stories table. No migration needed.")
            return
        
        print("Adding 'persona' column to user_stories table...")
        
        # Add the column
        conn.execute(text(
            "ALTER TABLE user_stories ADD COLUMN persona VARCHAR(100)"
        ))
        
        # Create index for the new column
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_stories_persona ON user_stories (persona)"
        ))
        
        conn.commit()
        
        print("✓ Migration complete! Column 'persona' added successfully.")
        print("\nThe persona field will be auto-extracted from story descriptions.")

if __name__ == "__main__":
    migrate_add_persona_column()
