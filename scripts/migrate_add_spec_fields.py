"""
Migration script to add specification fields to products table.

Adds:
- technical_spec (TEXT)
- spec_file_path (VARCHAR)
- spec_loaded_at (DATETIME)

Run with: python scripts/migrate_add_spec_fields.py
"""

import sqlite3
from pathlib import Path

# Database path
DB_PATH = "agile_simple.db"

def migrate():
    """Add specification fields to products table."""
    
    # Check if database exists
    if not Path(DB_PATH).exists():
        print(f"❌ Database not found: {DB_PATH}")
        print("   Create a new database by running the app first.")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(products)")
        columns = [row[1] for row in cursor.fetchall()]
        
        migrations_needed = []
        if 'technical_spec' not in columns:
            migrations_needed.append('technical_spec')
        if 'spec_file_path' not in columns:
            migrations_needed.append('spec_file_path')
        if 'spec_loaded_at' not in columns:
            migrations_needed.append('spec_loaded_at')
        
        if not migrations_needed:
            print("✅ Database already up to date! No migration needed.")
            return True
        
        print(f"🔧 Adding columns to products table: {', '.join(migrations_needed)}")
        
        # Add columns (SQLite allows adding columns one at a time)
        if 'technical_spec' in migrations_needed:
            cursor.execute("ALTER TABLE products ADD COLUMN technical_spec TEXT")
            print("   ✓ Added technical_spec (TEXT)")
        
        if 'spec_file_path' in migrations_needed:
            cursor.execute("ALTER TABLE products ADD COLUMN spec_file_path VARCHAR")
            print("   ✓ Added spec_file_path (VARCHAR)")
        
        if 'spec_loaded_at' in migrations_needed:
            cursor.execute("ALTER TABLE products ADD COLUMN spec_loaded_at DATETIME")
            print("   ✓ Added spec_loaded_at (DATETIME)")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
        # Verify
        cursor.execute("PRAGMA table_info(products)")
        all_columns = [row[1] for row in cursor.fetchall()]
        print(f"\n📋 Products table now has {len(all_columns)} columns:")
        for col in all_columns:
            print(f"   - {col}")
        
        return True
        
    except sqlite3.Error as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE MIGRATION: Add Specification Fields")
    print("=" * 60)
    print()
    
    success = migrate()
    
    if success:
        print("\n✨ You can now run the app with the new specification features!")
    else:
        print("\n⚠️  Migration failed. Check the error above.")
        print("   If you want to start fresh, delete agile_simple.db and run the app.")
