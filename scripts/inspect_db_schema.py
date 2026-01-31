"""Inspect runtime database schema."""
import os
import sqlite3
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def _get_db_path() -> str:
    """Resolve DB path from PROJECT_TCC_DB_URL (sqlite only) or fallback."""
    db_url = os.environ.get("PROJECT_TCC_DB_URL", "sqlite:///./agile_simple.db")
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "", 1)
    if db_url.startswith("sqlite://"):
        return db_url.replace("sqlite://", "", 1)
    return "agile_simple.db"


DB_PATH = _get_db_path()

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# List tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()
print("Tables in database:")
for t in tables:
    print(f"  - {t[0]}")

print()

# Inspect compiled_spec_authority
for tbl in ["compiled_spec_authority", "spec_registry", "spec_authority_acceptance"]:
    cursor.execute(f"PRAGMA table_info({tbl})")
    cols = cursor.fetchall()
    print(f"{tbl} has {len(cols)} columns:")
    for c in cols:
        print(f"  {c[0]}: {c[1]} ({c[2]}) nullable={c[3]}")
    print()

conn.close()
