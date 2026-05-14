"""Stable response envelopes for agent workbench commands."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "tcc.cli.v1"


@dataclass(frozen=True)
class WorkbenchWarning:
    """Recoverable command warning included in an envelope."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dictionary payload."""
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "remediation": list(self.remediation),
        }


@dataclass(frozen=True)
class WorkbenchError:
    """Command error included in a failed envelope."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: list[str] = field(default_factory=list)
    exit_code: int = 1
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dictionary payload."""
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "remediation": list(self.remediation),
            "exit_code": self.exit_code,
            "retryable": self.retryable,
        }


def utc_now_iso() -> str:
    """Return the current UTC timestamp in CLI envelope format."""
    return (
        datetime.now(tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def success_envelope(
    *,
    command: str,
    data: dict[str, Any] | list[Any],
    warnings: list[WorkbenchWarning] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a successful command response envelope."""
    return {
        "ok": True,
        "data": data,
        "warnings": [warning.to_dict() for warning in warnings or []],
        "errors": [],
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "command": command,
            "generated_at": generated_at or utc_now_iso(),
        },
    }


def error_envelope(
    *,
    command: str,
    error: WorkbenchError,
    warnings: list[WorkbenchWarning] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a failed command response envelope."""
    return {
        "ok": False,
        "data": None,
        "warnings": [warning.to_dict() for warning in warnings or []],
        "errors": [error.to_dict()],
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "command": command,
            "generated_at": generated_at or utc_now_iso(),
        },
    }
