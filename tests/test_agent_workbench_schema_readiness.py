"""Tests for read-only schema readiness checks."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from models.core import Product
from services.agent_workbench.schema_readiness import (
    SchemaRequirement,
    check_schema_readiness,
)


def test_check_schema_readiness_reports_missing_table() -> None:
    """Return missing table columns as structured data."""
    engine = create_engine("sqlite:///:memory:")

    result = check_schema_readiness(
        engine,
        [SchemaRequirement(table="products", columns=("product_id", "name"))],
    )

    assert result.ok is False
    assert result.missing == {"products": ["product_id", "name"]}


def test_check_schema_readiness_does_not_create_missing_sqlite_file(
    tmp_path: Path,
) -> None:
    """Report missing requirements without creating an absent SQLite file."""
    db_path = tmp_path / "missing.sqlite3"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    result = check_schema_readiness(
        engine,
        [SchemaRequirement(table="products", columns=("product_id", "name"))],
    )

    assert result.ok is False
    assert result.missing == {"products": ["product_id", "name"]}
    assert not db_path.exists()


def test_check_schema_readiness_reports_missing_columns() -> None:
    """Report missing columns without running migrations."""
    engine = create_engine("sqlite:///:memory:")
    Product.__table__.create(engine)

    result = check_schema_readiness(
        engine,
        [SchemaRequirement(table="products", columns=("product_id", "not_a_column"))],
    )

    assert result.ok is False
    assert result.missing == {"products": ["not_a_column"]}


def test_check_schema_readiness_accepts_existing_columns() -> None:
    """Accept an existing table with all required columns."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    result = check_schema_readiness(
        engine,
        [SchemaRequirement(table="products", columns=("product_id", "name"))],
    )

    assert result.ok is True
    assert result.missing == {}


def test_schema_requirement_rejects_bare_string_columns() -> None:
    """Reject a string because it would be treated as character columns."""
    with pytest.raises(TypeError, match="columns must be a sequence of column names"):
        SchemaRequirement(table="products", columns="product_id")
