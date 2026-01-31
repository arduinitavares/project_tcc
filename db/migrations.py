"""
Database schema migration utilities.

This module provides idempotent migrations to ensure the runtime database
schema matches the SQLModel definitions. It is designed to run at app startup
and safely handle schema drift without data loss.

Design:
- All migrations are idempotent (safe to run multiple times).
- Migrations only ADD columns/tables, never DROP or modify existing data.
- Each migration logs its action for observability.
- Failures are raised as RuntimeError with clear messages.

Usage:
    from db.migrations import ensure_schema_current
    ensure_schema_current(engine)
"""

import logging
from typing import List, Set

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _get_existing_tables(engine: Engine) -> Set[str]:
    """Return set of table names that exist in the database."""
    inspector = inspect(engine)
    return set(inspector.get_table_names())


def _get_existing_columns(engine: Engine, table_name: str) -> Set[str]:
    """Return set of column names for a table, or empty set if table doesn't exist."""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    columns = inspector.get_columns(table_name)
    return {col["name"] for col in columns}


def _ensure_table_exists(engine: Engine, table_name: str, create_sql: str) -> bool:
    """
    Ensure a table exists, creating it if necessary.
    
    Returns True if the table was created, False if it already existed.
    """
    existing_tables = _get_existing_tables(engine)
    if table_name in existing_tables:
        return False
    
    logger.info(
        "db.migration.create_table",
        extra={"table_name": table_name},
    )
    with engine.begin() as conn:
        conn.execute(text(create_sql))
    return True


def _ensure_column_exists(
    engine: Engine,
    table_name: str,
    column_name: str,
    column_def: str,
) -> bool:
    """
    Ensure a column exists in a table, adding it if necessary.
    
    Returns True if the column was added, False if it already existed.
    """
    existing_columns = _get_existing_columns(engine, table_name)
    if column_name in existing_columns:
        return False
    
    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
    logger.info(
        "db.migration.add_column",
        extra={"table_name": table_name, "column_name": column_name},
    )
    with engine.begin() as conn:
        conn.execute(text(alter_sql))
    return True


# =============================================================================
# SPEC AUTHORITY TABLES MIGRATION
# =============================================================================

SPEC_REGISTRY_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS spec_registry (
    spec_version_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    spec_hash VARCHAR NOT NULL,
    content TEXT,
    content_ref VARCHAR,
    status VARCHAR DEFAULT 'draft',
    created_at DATETIME NOT NULL,
    approved_at DATETIME,
    approved_by VARCHAR,
    approval_notes TEXT
)
"""

COMPILED_SPEC_AUTHORITY_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS compiled_spec_authority (
    authority_id INTEGER PRIMARY KEY,
    spec_version_id INTEGER NOT NULL UNIQUE REFERENCES spec_registry(spec_version_id),
    compiler_version VARCHAR NOT NULL,
    prompt_hash VARCHAR NOT NULL,
    compiled_at DATETIME NOT NULL,
    compiled_artifact_json TEXT,
    scope_themes TEXT NOT NULL,
    invariants TEXT NOT NULL,
    eligible_feature_ids TEXT NOT NULL,
    rejected_features TEXT,
    spec_gaps TEXT
)
"""

SPEC_AUTHORITY_ACCEPTANCE_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS spec_authority_acceptance (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    spec_version_id INTEGER NOT NULL REFERENCES spec_registry(spec_version_id),
    status VARCHAR NOT NULL,
    policy VARCHAR NOT NULL,
    decided_by VARCHAR NOT NULL,
    decided_at DATETIME NOT NULL,
    rationale TEXT,
    compiler_version VARCHAR NOT NULL,
    prompt_hash VARCHAR NOT NULL,
    spec_hash VARCHAR NOT NULL
)
"""


def migrate_spec_authority_tables(engine: Engine) -> List[str]:
    """
    Ensure all spec authority tables exist with required columns.
    
    Returns list of applied migration actions.
    """
    actions: List[str] = []
    
    # 1. Ensure spec_registry table exists
    if _ensure_table_exists(engine, "spec_registry", SPEC_REGISTRY_CREATE_SQL):
        actions.append("created table: spec_registry")
    
    # 2. Ensure compiled_spec_authority table exists
    if _ensure_table_exists(
        engine, "compiled_spec_authority", COMPILED_SPEC_AUTHORITY_CREATE_SQL
    ):
        actions.append("created table: compiled_spec_authority")
    else:
        # Table exists — ensure compiled_artifact_json column exists
        if _ensure_column_exists(
            engine,
            "compiled_spec_authority",
            "compiled_artifact_json",
            "TEXT",
        ):
            actions.append("added column: compiled_spec_authority.compiled_artifact_json")
    
    # 3. Ensure spec_authority_acceptance table exists
    if _ensure_table_exists(
        engine, "spec_authority_acceptance", SPEC_AUTHORITY_ACCEPTANCE_CREATE_SQL
    ):
        actions.append("created table: spec_authority_acceptance")
    
    return actions


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def ensure_schema_current(engine: Engine) -> None:
    """
    Run all idempotent migrations to ensure schema is current.
    
    This function is safe to call at every app startup. It will:
    - Create missing tables
    - Add missing columns to existing tables
    - Log all actions taken
    - Skip migrations that are already applied
    
    Raises:
        RuntimeError: If a migration fails (e.g., SQL error)
    """
    logger.info("db.migration.start", extra={})
    
    try:
        actions = migrate_spec_authority_tables(engine)
        
        if actions:
            for action in actions:
                logger.info(
                    "db.migration.applied",
                    extra={"action": action},
                )
            logger.info(
                "db.migration.complete",
                extra={"actions_count": len(actions)},
            )
        else:
            logger.info("db.migration.skip", extra={"reason": "schema_current"})
            
    except Exception as exc:
        logger.error(
            "db.migration.fail",
            extra={"error": str(exc), "error_type": type(exc).__name__},
        )
        raise RuntimeError(
            f"Database migration failed: {exc}. "
            "If this persists, consider deleting the database file and restarting."
        ) from exc
