# pylint: disable=not-callable, no-member
# agile_sqlmodel.py

"""
Defines the Agile project management schema using SQLModel.

This script creates all 12 tables, including link models for
many-to-many relationships, and sets up a SQLite database.

This version fixes the 'utcnow' deprecation warning and the
'func.now' runtime error.
"""

from importlib import import_module
import sys

# When this compatibility shim is executed as a script, models.core may import
# it again by module name while exports are still being populated. Register the
# current module under the canonical name up front so that path resolves to this
# in-flight module instead of executing the file twice.
if __name__ == "__main__":
    sys.modules.setdefault("agile_sqlmodel", sys.modules[__name__])

from models.core import (
    Epic,
    Feature,
    Product,
    ProductPersona,
    ProductTeam,
    Sprint,
    SprintStory,
    Task,
    Team,
    TeamMember,
    TeamMembership,
    Theme,
    UserStory,
)
from models.events import (
    StoryCompletionLog,
    TaskExecutionLog,
    WorkflowEvent,
)
from models.enums import (
    SpecAuthorityStatus,
    SprintStatus,
    StoryResolution,
    StoryStatus,
    TaskAcceptanceResult,
    TaskStatus,
    TeamRole,
    TimeFrame,
    WorkflowEventType,
)
from models.specs import (
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
    SpecRegistry,
)

# --- 1. Enums for Status Fields ---


def _db_module():
    """Load models.db lazily so model imports stay DB-config agnostic."""
    return import_module("models.db")


def __getattr__(name: str):
    """Lazily expose DB globals so importing this shim does not require DB env."""
    if name in {
        "DB_URL",
        "engine",
        "get_database_url",
        "get_engine",
        "create_db_and_tables",
        "ensure_business_db_ready",
    }:
        value = getattr(_db_module(), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    # This makes the script runnable with explicit environment configuration.
    _db_module().create_db_and_tables()
