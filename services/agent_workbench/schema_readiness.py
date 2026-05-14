"""Read-only schema readiness checks for CLI projections."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class SchemaRequirement:
    """Required table and columns for a projection."""

    table: str
    columns: Sequence[str]

    def __post_init__(self) -> None:
        """Normalize columns while rejecting bare strings."""
        if isinstance(self.columns, str):
            message = "columns must be a sequence of column names"
            raise TypeError(message)
        object.__setattr__(self, "columns", tuple(self.columns))


@dataclass(frozen=True)
class SchemaReadiness:
    """Schema readiness result."""

    ok: bool
    missing: dict[str, list[str]]


def check_schema_readiness(
    engine: Engine,
    requirements: Sequence[SchemaRequirement],
) -> SchemaReadiness:
    """Return missing schema elements without creating or migrating anything."""
    if _is_missing_sqlite_file(engine):
        return SchemaReadiness(ok=False, missing=_missing_all(requirements))

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing: dict[str, list[str]] = {}

    for requirement in requirements:
        if requirement.table not in table_names:
            missing[requirement.table] = list(requirement.columns)
            continue

        existing_columns = {
            column["name"] for column in inspector.get_columns(requirement.table)
        }
        missing_columns = [
            column for column in requirement.columns if column not in existing_columns
        ]
        if missing_columns:
            missing[requirement.table] = missing_columns

    return SchemaReadiness(ok=not missing, missing=missing)


def _is_missing_sqlite_file(engine: Engine) -> bool:
    """Return whether a SQLite file URL targets an absent database file."""
    if not engine.url.drivername.startswith("sqlite"):
        return False

    database = engine.url.database
    if database in {None, "", ":memory:"}:
        return False

    return not Path(database).exists()


def _missing_all(requirements: Sequence[SchemaRequirement]) -> dict[str, list[str]]:
    """Return every required column as missing for absent schema storage."""
    return {
        requirement.table: list(requirement.columns) for requirement in requirements
    }
