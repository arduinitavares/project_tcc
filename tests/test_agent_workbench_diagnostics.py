"""Tests for agent workbench diagnostics payloads."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from db.migrations import ensure_schema_current
from services.agent_workbench.diagnostics import doctor_payload, schema_check_payload
from services.agent_workbench.version import STORAGE_SCHEMA_VERSION


def test_schema_check_reports_ready_business_db(engine: Engine) -> None:
    """Report ready when business contract tables are present."""
    ensure_schema_current(engine)

    payload = schema_check_payload(
        business_engine=engine,
        session_db_url="sqlite:///:memory:",
    )

    assert payload["business_db"] == {
        "ok": True,
        "status": "ok",
        "required_version": STORAGE_SCHEMA_VERSION,
        "version_source": "agent_workbench_schema_versions",
        "checks": {
            "schema_versions_table": True,
            "cli_mutation_ledger_table": True,
        },
        "missing": [],
    }
    assert payload["workflow_session_store"] == {
        "ok": True,
        "status": "ok",
        "required_version": None,
        "version_source": "unavailable",
        "checks": {
            "configured": True,
            "sqlite_url": True,
            "readable_writable_mode": True,
        },
    }


def test_schema_check_reports_missing_business_contract_tables() -> None:
    """Report missing contract tables without migrating an empty database."""
    empty_engine = create_engine("sqlite:///:memory:")

    payload = schema_check_payload(
        business_engine=empty_engine,
        session_db_url="sqlite:///:memory:",
    )

    assert payload["business_db"]["ok"] is False
    assert payload["business_db"]["status"] == "blocked"
    assert payload["business_db"]["checks"] == {
        "schema_versions_table": False,
        "cli_mutation_ledger_table": False,
    }
    assert payload["business_db"]["missing"] == [
        "agent_workbench_schema_versions",
        "cli_mutation_ledger",
    ]


def test_doctor_reports_cwd_and_central_repo_root(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report caller cwd separately from the central repository root."""
    ensure_schema_current(engine)
    monkeypatch.chdir(tmp_path)

    payload = doctor_payload(
        business_engine=engine,
        session_db_url="sqlite:///:memory:",
    )

    assert payload["caller_cwd"] == {
        "ok": True,
        "status": "ok",
        "path": str(tmp_path.resolve()),
    }
    central_repo_root = payload["central_repo_root"]
    assert central_repo_root["ok"] is True
    assert central_repo_root["status"] == "ok"
    assert central_repo_root["path"].endswith("cli-contract-hardening-phase-2a")
    assert central_repo_root["path"] != str(tmp_path.resolve())
    assert payload["business_db"]["status"] == "ok"
    assert payload["workflow_session_store"]["status"] == "ok"
