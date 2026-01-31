"""Tests for runtime DB schema migrations."""

import logging
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel, create_engine


def _create_legacy_compiled_spec_authority(engine) -> None:
    """Create compiled_spec_authority table without compiled_artifact_json column."""
    legacy_sql = """
    CREATE TABLE IF NOT EXISTS compiled_spec_authority (
        authority_id INTEGER PRIMARY KEY,
        spec_version_id INTEGER NOT NULL UNIQUE REFERENCES spec_registry(spec_version_id),
        compiler_version VARCHAR NOT NULL,
        prompt_hash VARCHAR NOT NULL,
        compiled_at DATETIME NOT NULL,
        scope_themes TEXT NOT NULL,
        invariants TEXT NOT NULL,
        eligible_feature_ids TEXT NOT NULL,
        rejected_features TEXT,
        spec_gaps TEXT
    )
    """
    with engine.begin() as conn:
        conn.execute(text(legacy_sql))


def _get_table_columns(engine, table_name: str) -> set[str]:
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


@pytest.mark.usefixtures("monkeypatch")
def test_authority_gate_runs_schema_migration(tmp_path: Path, monkeypatch, caplog):
    """Ensure Authority Gate triggers schema migration for legacy DBs."""
    db_path = tmp_path / "legacy_authority.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    # Create legacy table missing compiled_artifact_json
    _create_legacy_compiled_spec_authority(engine)

    # Create the rest of the tables (compiled_spec_authority will remain legacy)
    # Import models to populate SQLModel metadata.
    import agile_sqlmodel  # pylint: disable=unused-import
    SQLModel.metadata.create_all(engine)

    import tools.spec_tools as spec_tools

    monkeypatch.setattr(spec_tools, "engine", engine)

    def _stub_update_spec_and_compile_authority(params, tool_context=None):
        return {
            "success": True,
            "accepted": True,
            "spec_version_id": 1,
            "compiler_version": "test",
        }

    monkeypatch.setattr(
        spec_tools,
        "update_spec_and_compile_authority",
        _stub_update_spec_and_compile_authority,
    )

    caplog.set_level(logging.INFO)
    spec_tools.ensure_accepted_spec_authority(1, spec_content="spec")

    columns = _get_table_columns(engine, "compiled_spec_authority")
    assert "compiled_artifact_json" in columns

    messages = [record.getMessage() for record in caplog.records]
    assert "db.migration.start" in messages
    assert "db.migration.applied" in messages
