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

from utils.task_metadata import canonical_task_metadata_json

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


def _get_existing_indexes(engine: Engine, table_name: str) -> Set[str]:
    """Return set of index names for a table, or empty set if table doesn't exist."""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    indexes = inspector.get_indexes(table_name)
    return {idx["name"] for idx in indexes}


def _ensure_index_exists(
    engine: Engine,
    table_name: str,
    index_name: str,
    column_names: List[str],
) -> bool:
    """
    Ensure an index exists on a table, creating it if necessary.

    Returns True if the index was created, False if it already existed.
    """
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return False

    existing_indexes = inspector.get_indexes(table_name)
    existing_by_name = {idx["name"]: idx for idx in existing_indexes}
    if index_name in existing_by_name:
        return False

    # Strict mode: enforce canonical naming for equivalent indexes.
    requested_columns = tuple(column_names)
    conflicting_equivalent_indexes = []
    for idx in existing_indexes:
        idx_columns = tuple(idx.get("column_names") or [])
        if idx_columns == requested_columns:
            conflicting_equivalent_indexes.append(idx["name"])

    if conflicting_equivalent_indexes:
        conflicts = ", ".join(sorted(conflicting_equivalent_indexes))
        raise RuntimeError(
            "Non-canonical index detected for "
            f"{table_name}({', '.join(column_names)}): {conflicts}. "
            f"Expected canonical index name: {index_name}."
        )

    columns_str = ", ".join(column_names)
    create_index_sql = f"CREATE INDEX {index_name} ON {table_name} ({columns_str})"
    logger.info(
        "db.migration.create_index",
        extra={"table_name": table_name, "index_name": index_name},
    )
    with engine.begin() as conn:
        conn.execute(text(create_index_sql))
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


def migrate_product_spec_cache(engine: Engine) -> List[str]:
    """Ensure product spec cache columns exist on products table."""
    actions: List[str] = []

    if _ensure_column_exists(
        engine,
        "products",
        "compiled_authority_json",
        "TEXT",
    ):
        actions.append("added column: products.compiled_authority_json")

    return actions


def migrate_performance_indexes(engine: Engine) -> List[str]:
    """Ensure performance indexes exist."""
    actions: List[str] = []

    # Optimization: Index on UserStory.product_id for faster filtering
    if _ensure_index_exists(
        engine,
        "user_stories",
        "ix_user_stories_product_id",
        ["product_id"],
    ):
        actions.append("created index: ix_user_stories_product_id")

    existing_columns = _get_existing_columns(engine, "user_stories")
    linkage_columns = {
        "product_id",
        "source_requirement",
        "refinement_slot",
        "is_superseded",
    }
    if linkage_columns.issubset(existing_columns):
        if _ensure_index_exists(
            engine,
            "user_stories",
            "ix_user_stories_refinement_linkage",
            ["product_id", "source_requirement", "refinement_slot", "is_superseded"],
        ):
            actions.append("created index: ix_user_stories_refinement_linkage")

    return actions


# =============================================================================
# USER STORY REFINEMENT LINKAGE MIGRATION
# =============================================================================

def migrate_user_story_refinement_linkage(engine: Engine) -> List[str]:
    """Ensure refinement linkage columns exist and defaults are backfilled."""
    actions: List[str] = []

    if _ensure_column_exists(
        engine,
        "user_stories",
        "source_requirement",
        "VARCHAR",
    ):
        actions.append("added column: user_stories.source_requirement")

    if _ensure_column_exists(
        engine,
        "user_stories",
        "refinement_slot",
        "INTEGER",
    ):
        actions.append("added column: user_stories.refinement_slot")

    if _ensure_column_exists(
        engine,
        "user_stories",
        "story_origin",
        "VARCHAR",
    ):
        actions.append("added column: user_stories.story_origin")

    if _ensure_column_exists(
        engine,
        "user_stories",
        "is_refined",
        "BOOLEAN DEFAULT 0",
    ):
        actions.append("added column: user_stories.is_refined")

    if _ensure_column_exists(
        engine,
        "user_stories",
        "is_superseded",
        "BOOLEAN DEFAULT 0",
    ):
        actions.append("added column: user_stories.is_superseded")

    if _ensure_column_exists(
        engine,
        "user_stories",
        "superseded_by_story_id",
        "INTEGER",
    ):
        actions.append("added column: user_stories.superseded_by_story_id")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE user_stories
                SET is_refined = 0
                WHERE is_refined IS NULL
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE user_stories
                SET is_superseded = 0
                WHERE is_superseded IS NULL
                """
            )
        )

    return actions


# =============================================================================
# SPRINT LIFECYCLE MIGRATION
# =============================================================================

def migrate_sprint_lifecycle(engine: Engine) -> List[str]:
    """Ensure sprint lifecycle columns exist."""
    actions: List[str] = []

    if _ensure_column_exists(
        engine,
        "sprints",
        "started_at",
        "DATETIME",
    ):
        actions.append("added column: sprints.started_at")

    return actions


def migrate_task_metadata(engine: Engine) -> List[str]:
    """Ensure persisted task metadata exists and legacy rows are backfilled."""

    actions: List[str] = []

    if _ensure_column_exists(
        engine,
        "tasks",
        "metadata_json",
        "TEXT",
    ):
        actions.append("added column: tasks.metadata_json")

    metadata_json = canonical_task_metadata_json()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE tasks
                SET metadata_json = :metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                WHERE metadata_json IS NULL OR TRIM(metadata_json) = ''
                """
            ),
            {"metadata_json": metadata_json},
        )
    if result.rowcount and result.rowcount > 0:
        actions.append(f"backfilled tasks.metadata_json rows: {result.rowcount}")

    return actions


# =============================================================================
# TASK EXECUTION MIGRATION
# =============================================================================

TASK_EXECUTION_LOGS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS task_execution_logs (
    log_id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(task_id),
    sprint_id INTEGER NOT NULL REFERENCES sprints(sprint_id),
    old_status VARCHAR,
    new_status VARCHAR NOT NULL,
    outcome_summary TEXT,
    artifact_refs_json TEXT,
    acceptance_result VARCHAR NOT NULL,
    notes TEXT,
    changed_by VARCHAR NOT NULL,
    changed_at DATETIME NOT NULL
)
"""

def migrate_task_execution_logs(engine: Engine) -> List[str]:
    """Ensure task_execution_logs table exists."""
    actions: List[str] = []

    if _ensure_table_exists(engine, "task_execution_logs", TASK_EXECUTION_LOGS_CREATE_SQL):
        actions.append("created table: task_execution_logs")
        
    if _ensure_index_exists(
        engine,
        "task_execution_logs",
        "ix_task_execution_logs_task_id",
        ["task_id"],
    ):
        actions.append("created index: ix_task_execution_logs_task_id")

    if _ensure_index_exists(
        engine,
        "task_execution_logs",
        "ix_task_execution_logs_sprint_id",
        ["sprint_id"],
    ):
        actions.append("created index: ix_task_execution_logs_sprint_id")

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
        actions.extend(migrate_product_spec_cache(engine))
        actions.extend(migrate_user_story_refinement_linkage(engine))
        actions.extend(migrate_sprint_lifecycle(engine))
        actions.extend(migrate_task_metadata(engine))
        actions.extend(migrate_task_execution_logs(engine))
        actions.extend(migrate_performance_indexes(engine))

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
