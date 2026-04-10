"""Inspect runtime database schema."""

import argparse
import sqlite3
from pathlib import Path

from utils.runtime_config import resolve_database_target


def resolve_db_path(explicit_db: str | None = None) -> str:
    """Resolve a DB path from CLI input or runtime configuration."""
    return resolve_database_target(
        explicit_db,
        env_name="PROJECT_TCC_DB_URL",
    ).sqlite_connect_target


def inspect_schema(db_path: str) -> None:
    """Print basic schema details for the target database."""
    if db_path != ":memory:" and not Path(db_path).exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    print("Tables in database:")
    for (table_name,) in tables:
        print(f"  - {table_name}")

    print()

    for table_name in [
        "compiled_spec_authority",
        "spec_registry",
        "spec_authority_acceptance",
    ]:
        cursor.execute(f"PRAGMA table_info({table_name})")
        cols = cursor.fetchall()
        print(f"{table_name} has {len(cols)} columns:")
        for column in cols:
            print(f"  {column[0]}: {column[1]} ({column[2]}) nullable={column[3]}")
        print()

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect the configured runtime database schema."
    )
    parser.add_argument(
        "db",
        nargs="?",
        help="Optional SQLite database path or sqlite:/// URL. Defaults to PROJECT_TCC_DB_URL.",
    )
    args = parser.parse_args()
    inspect_schema(resolve_db_path(args.db))


if __name__ == "__main__":
    main()
