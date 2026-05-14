"""Tests for centralized runtime configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from utils.runtime_config import (
    RuntimeConfigError,
    clear_runtime_config_cache,
    get_business_db_target,
    get_database_echo,
    get_session_db_target,
    resolve_database_target,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clear_runtime_cache() -> object:
    clear_runtime_config_cache()
    yield
    clear_runtime_config_cache()


def test_business_db_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify business db url is required."""
    monkeypatch.delenv("PROJECT_TCC_DB_URL", raising=False)

    with pytest.raises(RuntimeConfigError, match="PROJECT_TCC_DB_URL"):
        get_business_db_target()


def test_session_db_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify session db url is required."""
    monkeypatch.setenv("PROJECT_TCC_DB_URL", "sqlite:///./db/spec_authority_dev.db")
    monkeypatch.delenv("PROJECT_TCC_SESSION_DB_URL", raising=False)

    with pytest.raises(RuntimeConfigError, match="PROJECT_TCC_SESSION_DB_URL"):
        get_session_db_target()


def test_legacy_business_db_filename_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify legacy business db filename is rejected."""
    monkeypatch.setenv("PROJECT_TCC_DB_URL", "sqlite:///./agile_simple.db")

    with pytest.raises(RuntimeConfigError, match="agile_simple.db"):  # noqa: RUF043
        get_business_db_target()


def test_legacy_session_db_filename_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify legacy session db filename is rejected."""
    monkeypatch.setenv("PROJECT_TCC_DB_URL", "sqlite:///./db/spec_authority_dev.db")
    monkeypatch.setenv("PROJECT_TCC_SESSION_DB_URL", "sqlite:///./agile_sqlmodel.db")

    with pytest.raises(RuntimeConfigError, match="agile_sqlmodel.db"):  # noqa: RUF043
        get_session_db_target()


def test_sqlite_targets_are_normalized_to_absolute_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify sqlite targets are normalized to absolute paths."""
    monkeypatch.setenv("PROJECT_TCC_DB_URL", "sqlite:///./db/spec_authority_dev.db")
    monkeypatch.setenv(
        "PROJECT_TCC_SESSION_DB_URL",
        "sqlite:///./db/spec_authority_session_dev.db",
    )

    business = get_business_db_target()
    session = get_session_db_target()

    assert business.sqlite_path is not None
    assert session.sqlite_path is not None
    assert business.sqlite_path.is_absolute()
    assert session.sqlite_path.is_absolute()
    assert business.sqlite_url.endswith("db/spec_authority_dev.db")
    assert session.sqlite_url.endswith("db/spec_authority_session_dev.db")


def test_session_db_must_be_distinct_from_business_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify session db must be distinct from business db."""
    shared_path = "sqlite:///./db/shared.sqlite3"
    monkeypatch.setenv("PROJECT_TCC_DB_URL", shared_path)
    monkeypatch.setenv("PROJECT_TCC_SESSION_DB_URL", shared_path)

    with pytest.raises(RuntimeConfigError, match="different SQLite file"):
        get_session_db_target()


def test_explicit_database_target_overrides_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify explicit database target overrides environment."""
    monkeypatch.setenv("PROJECT_TCC_DB_URL", "sqlite:///./db/from-env.db")
    explicit_path = tmp_path / "override.sqlite3"

    target = resolve_database_target(
        str(explicit_path),
        env_name="PROJECT_TCC_DB_URL",
    )

    assert target.sqlite_path == explicit_path.resolve()
    assert target.sqlite_connect_target == str(explicit_path.resolve())


def test_database_echo_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify database echo defaults to false."""
    monkeypatch.delenv("PROJECT_TCC_DB_ECHO", raising=False)

    assert get_database_echo() is False


def test_database_echo_honors_true_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify database echo honors true env."""
    monkeypatch.setenv("PROJECT_TCC_DB_ECHO", "true")

    assert get_database_echo() is True
