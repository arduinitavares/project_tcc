"""Registered agent workbench CLI error codes."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from services.agent_workbench.envelope import WorkbenchError


@dataclass(frozen=True)
class ErrorMetadata:
    """Stable metadata for a registered CLI error code."""

    code: str
    default_exit_code: int
    retryable: bool
    description: str


class ErrorCode(str, Enum):
    """Registered agent workbench CLI error codes."""

    INVALID_COMMAND = "INVALID_COMMAND"
    COMMAND_EXCEPTION = "COMMAND_EXCEPTION"
    COMMAND_NOT_IMPLEMENTED = "COMMAND_NOT_IMPLEMENTED"
    SCHEMA_NOT_READY = "SCHEMA_NOT_READY"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    STORY_NOT_FOUND = "STORY_NOT_FOUND"
    SPEC_VERSION_NOT_FOUND = "SPEC_VERSION_NOT_FOUND"
    AUTHORITY_NOT_ACCEPTED = "AUTHORITY_NOT_ACCEPTED"
    AUTHORITY_NOT_COMPILED = "AUTHORITY_NOT_COMPILED"
    AUTHORITY_ACCEPTANCE_MISMATCH = "AUTHORITY_ACCEPTANCE_MISMATCH"
    AUTHORITY_INVARIANTS_INVALID = "AUTHORITY_INVARIANTS_INVALID"
    STALE_STATE = "STALE_STATE"
    STALE_FINGERPRINT = "STALE_FINGERPRINT"
    STALE_CONTEXT_FINGERPRINT = "STALE_CONTEXT_FINGERPRINT"
    STALE_AUTHORITY_VERSION = "STALE_AUTHORITY_VERSION"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    ACTIVE_STATE_BLOCKS_DELETE = "ACTIVE_STATE_BLOCKS_DELETE"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    MUTATION_FAILED = "MUTATION_FAILED"
    MUTATION_ROLLBACK = "MUTATION_ROLLBACK"
    MUTATION_IN_PROGRESS = "MUTATION_IN_PROGRESS"
    MUTATION_RECOVERY_REQUIRED = "MUTATION_RECOVERY_REQUIRED"
    MUTATION_RESUME_CONFLICT = "MUTATION_RESUME_CONFLICT"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    MUTATION_NOT_FOUND = "MUTATION_NOT_FOUND"


_ERROR_REGISTRY: dict[ErrorCode, ErrorMetadata] = {
    ErrorCode.INVALID_COMMAND: ErrorMetadata(
        code=ErrorCode.INVALID_COMMAND.value,
        default_exit_code=2,
        retryable=False,
        description="The command is invalid.",
    ),
    ErrorCode.COMMAND_EXCEPTION: ErrorMetadata(
        code=ErrorCode.COMMAND_EXCEPTION.value,
        default_exit_code=1,
        retryable=False,
        description="The command failed with an unexpected exception.",
    ),
    ErrorCode.COMMAND_NOT_IMPLEMENTED: ErrorMetadata(
        code=ErrorCode.COMMAND_NOT_IMPLEMENTED.value,
        default_exit_code=2,
        retryable=False,
        description="The command is registered but not implemented.",
    ),
    ErrorCode.SCHEMA_NOT_READY: ErrorMetadata(
        code=ErrorCode.SCHEMA_NOT_READY.value,
        default_exit_code=3,
        retryable=False,
        description="The storage schema is not ready for this command.",
    ),
    ErrorCode.PROJECT_NOT_FOUND: ErrorMetadata(
        code=ErrorCode.PROJECT_NOT_FOUND.value,
        default_exit_code=4,
        retryable=False,
        description="The requested project was not found.",
    ),
    ErrorCode.STORY_NOT_FOUND: ErrorMetadata(
        code=ErrorCode.STORY_NOT_FOUND.value,
        default_exit_code=4,
        retryable=False,
        description="The requested story was not found.",
    ),
    ErrorCode.SPEC_VERSION_NOT_FOUND: ErrorMetadata(
        code=ErrorCode.SPEC_VERSION_NOT_FOUND.value,
        default_exit_code=4,
        retryable=False,
        description="The requested spec version was not found.",
    ),
    ErrorCode.AUTHORITY_NOT_ACCEPTED: ErrorMetadata(
        code=ErrorCode.AUTHORITY_NOT_ACCEPTED.value,
        default_exit_code=4,
        retryable=False,
        description="The project has no accepted authority.",
    ),
    ErrorCode.AUTHORITY_NOT_COMPILED: ErrorMetadata(
        code=ErrorCode.AUTHORITY_NOT_COMPILED.value,
        default_exit_code=4,
        retryable=False,
        description="The selected spec version has no compiled authority.",
    ),
    ErrorCode.AUTHORITY_ACCEPTANCE_MISMATCH: ErrorMetadata(
        code=ErrorCode.AUTHORITY_ACCEPTANCE_MISMATCH.value,
        default_exit_code=4,
        retryable=False,
        description="Accepted authority does not match compiled authority.",
    ),
    ErrorCode.AUTHORITY_INVARIANTS_INVALID: ErrorMetadata(
        code=ErrorCode.AUTHORITY_INVARIANTS_INVALID.value,
        default_exit_code=4,
        retryable=False,
        description="Authority invariants are invalid.",
    ),
    ErrorCode.STALE_STATE: ErrorMetadata(
        code=ErrorCode.STALE_STATE.value,
        default_exit_code=10,
        retryable=True,
        description="State changed before the command could complete.",
    ),
    ErrorCode.STALE_FINGERPRINT: ErrorMetadata(
        code=ErrorCode.STALE_FINGERPRINT.value,
        default_exit_code=11,
        retryable=True,
        description="The supplied state fingerprint is stale.",
    ),
    ErrorCode.STALE_CONTEXT_FINGERPRINT: ErrorMetadata(
        code=ErrorCode.STALE_CONTEXT_FINGERPRINT.value,
        default_exit_code=11,
        retryable=True,
        description="The supplied context fingerprint is stale.",
    ),
    ErrorCode.STALE_AUTHORITY_VERSION: ErrorMetadata(
        code=ErrorCode.STALE_AUTHORITY_VERSION.value,
        default_exit_code=12,
        retryable=True,
        description="The supplied authority version is stale.",
    ),
    ErrorCode.CONFIRMATION_REQUIRED: ErrorMetadata(
        code=ErrorCode.CONFIRMATION_REQUIRED.value,
        default_exit_code=20,
        retryable=False,
        description="The command requires explicit confirmation.",
    ),
    ErrorCode.ACTIVE_STATE_BLOCKS_DELETE: ErrorMetadata(
        code=ErrorCode.ACTIVE_STATE_BLOCKS_DELETE.value,
        default_exit_code=21,
        retryable=False,
        description="Active state blocks the requested delete.",
    ),
    ErrorCode.SCHEMA_VERSION_MISMATCH: ErrorMetadata(
        code=ErrorCode.SCHEMA_VERSION_MISMATCH.value,
        default_exit_code=3,
        retryable=False,
        description="The storage schema version does not match this command.",
    ),
    ErrorCode.MUTATION_FAILED: ErrorMetadata(
        code=ErrorCode.MUTATION_FAILED.value,
        default_exit_code=1,
        retryable=False,
        description="The mutation failed.",
    ),
    ErrorCode.MUTATION_ROLLBACK: ErrorMetadata(
        code=ErrorCode.MUTATION_ROLLBACK.value,
        default_exit_code=1,
        retryable=False,
        description="The mutation was rolled back.",
    ),
    ErrorCode.MUTATION_IN_PROGRESS: ErrorMetadata(
        code=ErrorCode.MUTATION_IN_PROGRESS.value,
        default_exit_code=13,
        retryable=True,
        description="A mutation is already in progress.",
    ),
    ErrorCode.MUTATION_RECOVERY_REQUIRED: ErrorMetadata(
        code=ErrorCode.MUTATION_RECOVERY_REQUIRED.value,
        default_exit_code=14,
        retryable=True,
        description="Mutation recovery is required before continuing.",
    ),
    ErrorCode.MUTATION_RESUME_CONFLICT: ErrorMetadata(
        code=ErrorCode.MUTATION_RESUME_CONFLICT.value,
        default_exit_code=15,
        retryable=False,
        description="The mutation cannot be resumed from this state.",
    ),
    ErrorCode.IDEMPOTENCY_KEY_REUSED: ErrorMetadata(
        code=ErrorCode.IDEMPOTENCY_KEY_REUSED.value,
        default_exit_code=16,
        retryable=False,
        description="The idempotency key was reused for a different mutation.",
    ),
    ErrorCode.MUTATION_NOT_FOUND: ErrorMetadata(
        code=ErrorCode.MUTATION_NOT_FOUND.value,
        default_exit_code=4,
        retryable=False,
        description="The requested mutation was not found.",
    ),
}


def _normalize_code(code: ErrorCode | str) -> ErrorCode:
    """Return a registered ErrorCode from enum or string input."""
    if isinstance(code, ErrorCode):
        return code
    return ErrorCode(code)


def error_metadata(code: ErrorCode | str) -> ErrorMetadata:
    """Return stable metadata for a registered error code."""
    return _ERROR_REGISTRY[_normalize_code(code)]


def registered_error_codes() -> set[str]:
    """Return the complete registered CLI error code set."""
    return {metadata.code for metadata in _ERROR_REGISTRY.values()}


def workbench_error(
    code: ErrorCode | str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    remediation: list[str] | None = None,
) -> WorkbenchError:
    """Build a WorkbenchError using registry defaults."""
    metadata = error_metadata(code)
    return WorkbenchError(
        code=metadata.code,
        message=metadata.description if message is None else message,
        details=dict(details or {}),
        remediation=list(remediation or []),
        exit_code=metadata.default_exit_code,
        retryable=metadata.retryable,
    )
