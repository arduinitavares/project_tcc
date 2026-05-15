"""Agent workbench diagnostics and schema readiness payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from services.agent_workbench.version import STORAGE_SCHEMA_VERSION
from utils.runtime_config import get_session_db_target

BUSINESS_SCHEMA_VERSION_TABLE = "agent_workbench_schema_versions"
BUSINESS_MUTATION_LEDGER_TABLE = "cli_mutation_ledger"


def schema_check_payload(
    *,
    business_engine: Engine | None = None,
    session_db_url: str | None = None,
) -> dict[str, Any]:
    """Return JSON-friendly schema readiness diagnostics."""
    return {
        "business_db": _business_db_payload(business_engine=business_engine),
        "workflow_session_store": _workflow_session_store_payload(
            session_db_url=session_db_url,
        ),
    }


def doctor_payload(
    *,
    business_engine: Engine | None = None,
    session_db_url: str | None = None,
) -> dict[str, Any]:
    """Return broader local diagnostics for CLI contract health."""
    payload = schema_check_payload(
        business_engine=business_engine,
        session_db_url=session_db_url,
    )
    payload["central_repo_root"] = _path_payload(_central_repo_root())
    payload["caller_cwd"] = _path_payload(Path.cwd())
    return payload


def _business_db_payload(*, business_engine: Engine | None) -> dict[str, Any]:
    """Return readiness for required business DB contract tables."""
    engine = (
        business_engine if business_engine is not None else _default_business_engine()
    )
    missing = [BUSINESS_SCHEMA_VERSION_TABLE, BUSINESS_MUTATION_LEDGER_TABLE]
    checks = {
        "schema_versions_table": False,
        "cli_mutation_ledger_table": False,
    }

    try:
        table_names = set(inspect(engine).get_table_names())
    except SQLAlchemyError:
        return {
            "ok": False,
            "status": "blocked",
            "required_version": STORAGE_SCHEMA_VERSION,
            "version_source": BUSINESS_SCHEMA_VERSION_TABLE,
            "checks": checks,
            "missing": missing,
        }

    checks = {
        "schema_versions_table": BUSINESS_SCHEMA_VERSION_TABLE in table_names,
        "cli_mutation_ledger_table": BUSINESS_MUTATION_LEDGER_TABLE in table_names,
    }
    missing = [
        table_name
        for table_name, present in (
            (BUSINESS_SCHEMA_VERSION_TABLE, checks["schema_versions_table"]),
            (BUSINESS_MUTATION_LEDGER_TABLE, checks["cli_mutation_ledger_table"]),
        )
        if not present
    ]
    ok = not missing
    return {
        "ok": ok,
        "status": "ok" if ok else "blocked",
        "required_version": STORAGE_SCHEMA_VERSION,
        "version_source": BUSINESS_SCHEMA_VERSION_TABLE,
        "checks": checks,
        "missing": missing,
    }


def _workflow_session_store_payload(*, session_db_url: str | None) -> dict[str, Any]:
    """Return conservative workflow session store readiness."""
    sqlite_url = (
        session_db_url if session_db_url is not None else _default_session_db_url()
    )
    configured = bool(sqlite_url)
    sqlite_ready = _is_sqlite_url(sqlite_url) if configured else False
    writable_mode = (
        _is_readable_writable_sqlite_mode(sqlite_url) if configured else False
    )
    ok = configured and sqlite_ready and writable_mode
    return {
        "ok": ok,
        "status": "ok" if ok else "blocked",
        "required_version": None,
        "version_source": "unavailable",
        "checks": {
            "configured": configured,
            "sqlite_url": sqlite_ready,
            "readable_writable_mode": writable_mode,
        },
    }


def _default_business_engine() -> Engine:
    """Return the configured business engine at call time."""
    from models import db as model_db

    return model_db.get_engine()


def _default_session_db_url() -> str:
    """Return the configured workflow session DB URL."""
    return get_session_db_target().sqlite_url


def _is_sqlite_url(value: str) -> bool:
    """Return whether the configured value is a SQLAlchemy SQLite URL."""
    try:
        return make_url(value).drivername.startswith("sqlite")
    except ValueError:
        return False


def _is_readable_writable_sqlite_mode(value: str) -> bool:
    """Return whether the SQLite URL is not explicitly read-only."""
    try:
        url = make_url(value)
    except ValueError:
        return False
    mode = url.query.get("mode")
    immutable = url.query.get("immutable")
    if mode == "ro" or immutable == "1":
        return False
    if not url.drivername.startswith("sqlite"):
        return False

    database = url.database
    if database in {None, "", ":memory:"}:
        return True

    path = Path(database)
    if path.exists():
        return path.is_file() and _can_read_write(path)
    return path.parent.exists()


def _can_read_write(path: Path) -> bool:
    """Return whether an existing database file allows read/write access."""
    try:
        with path.open("r+b"):
            return True
    except OSError:
        return False


def _central_repo_root() -> Path:
    """Resolve the AgileForge repository root from this package location."""
    return Path(__file__).resolve().parents[2]


def _path_payload(path: Path) -> dict[str, Any]:
    """Return path existence as an ok/blocked diagnostic."""
    resolved = path.resolve()
    ok = resolved.exists()
    return {
        "ok": ok,
        "status": "ok" if ok else "blocked",
        "path": str(resolved),
    }
