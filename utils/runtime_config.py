"""Centralized runtime configuration and identities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _REPO_ROOT / ".env"
_LEGACY_DB_FILENAMES = frozenset({"agile_simple.db", "agile_sqlmodel.db"})
_TRUE_VALUES = {"1", "true", "yes", "on"}


class RuntimeConfigError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class DatabaseTarget:
    """Resolved database target for both SQLAlchemy and sqlite3 callers."""

    source: str
    sqlite_url: str
    sqlite_path: Optional[Path]

    @property
    def sqlite_connect_target(self) -> str:
        if self.sqlite_path is None:
            return ":memory:"
        return str(self.sqlite_path)


@dataclass(frozen=True)
class RunnerIdentity:
    """Stable app/user namespace for an ADK runner."""

    app_name: str
    user_id: str


WORKFLOW_RUNNER_IDENTITY = RunnerIdentity(
    app_name="agile_orchestrator",
    user_id="local_developer",
)
VISION_RUNNER_IDENTITY = RunnerIdentity(
    app_name="product_vision_tool",
    user_id="dashboard_vision",
)
BACKLOG_RUNNER_IDENTITY = RunnerIdentity(
    app_name="backlog_primer",
    user_id="dashboard_backlog",
)
ROADMAP_RUNNER_IDENTITY = RunnerIdentity(
    app_name="roadmap_builder",
    user_id="dashboard_roadmap",
)
STORY_RUNNER_IDENTITY = RunnerIdentity(
    app_name="user_story_writer",
    user_id="dashboard_story",
)
SPEC_AUTHORITY_COMPILER_IDENTITY = RunnerIdentity(
    app_name="spec_authority_compiler",
    user_id="spec_compiler",
)
SPEC_VALIDATOR_IDENTITY = RunnerIdentity(
    app_name="spec_validator_agent",
    user_id="spec_validator",
)


def load_runtime_env() -> None:
    """Load the repository .env file once for all runtime consumers."""
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)


load_runtime_env()


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeConfigError(
            f"Missing required environment variable: {name}. "
            f"Add it to {_ENV_PATH.name} or export it before running the app."
        )
    return value


def get_optional_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read an optional environment variable after loading .env once."""
    value = os.environ.get(name)
    if value is None:
        return default
    stripped = value.strip()
    if not stripped and default is not None:
        return default
    return stripped


def get_bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    value = get_optional_env(name)
    if value is None:
        return default
    return value.lower() in _TRUE_VALUES


def get_int_env(name: str, default: int) -> int:
    """Read an integer environment variable with a validated default."""
    value = get_optional_env(name)
    if value is None:
        return default
    return int(value)


def _reject_legacy_db_name(path: Path, source: str) -> None:
    if path.name in _LEGACY_DB_FILENAMES:
        raise RuntimeConfigError(
            f"{source} resolves to legacy database filename {path.name!r}. "
            "Legacy root database files are no longer supported."
        )


def _normalize_sqlite_target(raw_value: str, *, source: str) -> DatabaseTarget:
    value = raw_value.strip()
    if not value:
        raise RuntimeConfigError(f"{source} must not be empty.")

    if value in {":memory:", "sqlite:///:memory:"}:
        return DatabaseTarget(source=source, sqlite_url="sqlite:///:memory:", sqlite_path=None)

    if value.startswith("sqlite:///"):
        raw_path = value.replace("sqlite:///", "", 1)
    elif value.startswith("sqlite://"):
        raise RuntimeConfigError(
            f"{source} must be a SQLite file URL of the form sqlite:///path/to/db.sqlite3 "
            f"or a filesystem path, got {value!r}."
        )
    elif "://" in value:
        raise RuntimeConfigError(
            f"{source} must point to a SQLite database, got unsupported URL {value!r}."
        )
    else:
        raw_path = value

    path = Path(raw_path)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    else:
        path = path.resolve()

    _reject_legacy_db_name(path, source)
    return DatabaseTarget(
        source=source,
        sqlite_url=f"sqlite:///{path.as_posix()}",
        sqlite_path=path,
    )


def resolve_database_target(
    explicit_value: Optional[str],
    *,
    env_name: str,
) -> DatabaseTarget:
    """Resolve an explicit DB argument or a required environment variable."""
    if explicit_value is not None and explicit_value.strip():
        return _normalize_sqlite_target(explicit_value, source="explicit database argument")
    return _normalize_sqlite_target(_require_env(env_name), source=env_name)


@lru_cache(maxsize=1)
def get_business_db_target() -> DatabaseTarget:
    """Return the configured business database target."""
    return resolve_database_target(None, env_name="PROJECT_TCC_DB_URL")


@lru_cache(maxsize=1)
def get_session_db_target() -> DatabaseTarget:
    """Return the configured session database target."""
    target = resolve_database_target(None, env_name="PROJECT_TCC_SESSION_DB_URL")
    business_target = get_business_db_target()
    if target.sqlite_path is not None and target.sqlite_path == business_target.sqlite_path:
        raise RuntimeConfigError(
            "PROJECT_TCC_SESSION_DB_URL must point to a different SQLite file than "
            "PROJECT_TCC_DB_URL."
        )
    return target


def get_openrouter_api_key() -> Optional[str]:
    """Return the OpenRouter API key, if configured."""
    return get_optional_env("OPEN_ROUTER_API_KEY")


@lru_cache(maxsize=1)
def get_database_echo() -> bool:
    """Return whether SQLAlchemy echo logging is enabled."""
    return get_bool_env("PROJECT_TCC_DB_ECHO", default=True)


def get_spec_validator_max_tokens(default: int = 4096) -> int:
    """Return the max token budget for the spec validator."""
    return get_int_env("SPEC_VALIDATOR_MAX_TOKENS", default)


def is_spec_compiler_schema_disabled() -> bool:
    """Return whether the spec compiler should skip output schema enforcement."""
    return get_bool_env("SPEC_COMPILER_DISABLE_SCHEMA", default=False)


def get_default_validation_mode(default: str = "deterministic") -> str:
    """Return the default spec validation mode."""
    return get_optional_env("SPEC_VALIDATION_DEFAULT_MODE", default) or default


def get_api_host(default: str = "0.0.0.0") -> str:
    """Return the API host for local runs."""
    return get_optional_env("PROJECT_TCC_API_HOST", default) or default


def get_api_port(default: int = 8000) -> int:
    """Return the API port for local runs."""
    return get_int_env("PROJECT_TCC_API_PORT", default)


def get_api_reload(default: bool = True) -> bool:
    """Return whether api.py should launch uvicorn in reload mode."""
    return get_bool_env("PROJECT_TCC_API_RELOAD", default)


def clear_runtime_config_cache() -> None:
    """Clear cached runtime settings for tests."""
    get_business_db_target.cache_clear()
    get_session_db_target.cache_clear()
    get_database_echo.cache_clear()
