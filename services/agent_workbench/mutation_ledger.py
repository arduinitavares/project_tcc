"""Durable mutation ledger for CLI idempotency and recovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from models.agent_workbench import CliMutationLedger
from services.agent_workbench.error_codes import ErrorCode, workbench_error

IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
MUTATION_IN_PROGRESS = "MUTATION_IN_PROGRESS"
MUTATION_RECOVERY_REQUIRED = "MUTATION_RECOVERY_REQUIRED"
MUTATION_RESUME_CONFLICT = "MUTATION_RESUME_CONFLICT"
MUTATION_NOT_FOUND = "MUTATION_NOT_FOUND"
DEFAULT_STALE_PENDING_TIMEOUT_SECONDS = 300
DEFAULT_LEASE_SECONDS = DEFAULT_STALE_PENDING_TIMEOUT_SECONDS
DEFAULT_CLI_RESUME_LEASE_OWNER = "agileforge-cli:mutation-resume"


class MutationStatus(StrEnum):
    """Stable mutation ledger states."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    VALIDATION_FAILED = "validation_failed"
    GUARD_REJECTED = "guard_rejected"
    DOMAIN_FAILED_NO_SIDE_EFFECTS = "domain_failed_no_side_effects"
    RECOVERY_REQUIRED = "recovery_required"


class RecoveryAction(StrEnum):
    """Finite recovery actions for incomplete mutations."""

    NONE = "none"
    RESUME_FROM_STEP = "resume_from_step"
    RECONCILE_THEN_RESUME = "reconcile_then_resume"
    MANUAL_INTERVENTION_REQUIRED = "manual_intervention_required"


@dataclass(frozen=True)
class LedgerLoadResult:
    """Result from creating or loading a mutation ledger row."""

    ledger: CliMutationLedger
    replayed: bool = False
    response: dict[str, Any] | None = None
    error_code: str | None = None


def _json_dump(value: object) -> str:
    """Dump deterministic JSON for persisted ledger blobs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_load(value: str | None) -> dict[str, Any] | list[Any] | None:
    """Load a persisted JSON object or array."""
    if not value:
        return None
    loaded = json.loads(value)
    if isinstance(loaded, (dict, list)):
        return loaded
    return None


def _json_blob(value: str | None) -> object:
    """Return a JSON-friendly value from a persisted JSON blob."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _completed_steps(row: CliMutationLedger) -> list[str]:
    loaded = _json_load(row.completed_steps_json)
    if isinstance(loaded, list):
        return [str(item) for item in loaded]
    return []


def _stale_pending_error(row: CliMutationLedger, now: datetime) -> dict[str, Any]:
    return {
        "code": "STALE_PENDING",
        "message": "Pending mutation lease expired.",
        "details": {"current_step": row.current_step},
        "retryable": True,
        "recorded_at": _utc_isoformat(now),
    }


def _utc_isoformat(value: datetime) -> str:
    """Return an ISO timestamp for the UTC instant represented by value."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _db_datetime(value: datetime) -> datetime:
    """Normalize datetimes to UTC-naive values for SQLite persistence.

    Naive inputs are treated as already UTC. Aware inputs are converted to the
    equivalent UTC instant before dropping tzinfo.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(tzinfo=None)


class MutationLedgerRepository:
    """Repository for mutation ledger compare-and-set transitions."""

    def __init__(self, *, engine: Engine) -> None:
        self._engine: Engine = engine

    def show_event(self, *, mutation_event_id: int) -> dict[str, Any]:
        """Return one mutation ledger event in a service envelope."""
        with Session(self._engine) as session:
            row = session.get(CliMutationLedger, mutation_event_id)
            if row is None:
                return _error_result(
                    code=ErrorCode.MUTATION_NOT_FOUND,
                    details={"mutation_event_id": mutation_event_id},
                    remediation=["agileforge mutation list"],
                )
            return _success_result(_row_payload(row))

    def list_events(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Return mutation ledger events filtered by project and status."""
        statement = select(CliMutationLedger)
        if project_id is not None:
            statement = statement.where(CliMutationLedger.project_id == project_id)
        if status is not None:
            statement = statement.where(CliMutationLedger.status == status)
        statement = statement.order_by(CliMutationLedger.mutation_event_id)

        with Session(self._engine) as session:
            rows = session.exec(statement).all()
            return _success_result({"items": [_row_payload(row) for row in rows]})

    def resume_event(
        self,
        *,
        mutation_event_id: int,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Acquire a recovery lease without performing domain recovery."""
        shown = self.show_event(mutation_event_id=mutation_event_id)
        if shown.get("ok") is not True:
            return shown

        result = self.acquire_resume_lease(
            mutation_event_id=mutation_event_id,
            lease_owner=_resume_lease_owner(correlation_id),
            now=datetime.now(UTC),
            lease_seconds=DEFAULT_LEASE_SECONDS,
        )
        data = _row_payload(result.ledger)
        if result.error_code is not None:
            return _error_result(
                code=result.error_code,
                details={"mutation_event_id": mutation_event_id},
                remediation=[
                    "agileforge mutation show "
                    f"--mutation-event-id {mutation_event_id}"
                ],
                data=data,
            )

        data["recovery"] = {
            "acquired": True,
            "domain_resume_required": True,
        }
        return _success_result(data)

    def create_or_load(
        self,
        *,
        command: str,
        idempotency_key: str,
        request_hash: str,
        project_id: int | None,
        correlation_id: str,
        changed_by: str,
        lease_owner: str,
        now: datetime,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> LedgerLoadResult:
        """Create a pending row or return the existing deterministic outcome."""
        db_now = _db_datetime(now)
        with Session(self._engine) as session:
            existing = session.exec(
                select(CliMutationLedger).where(
                    CliMutationLedger.command == command,
                    CliMutationLedger.idempotency_key == idempotency_key,
                )
            ).first()
            if existing is not None:
                return self._existing_result(
                    session=session,
                    row=existing,
                    request_hash=request_hash,
                    now=now,
                )

            row = CliMutationLedger(
                command=command,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                project_id=project_id,
                correlation_id=correlation_id,
                changed_by=changed_by,
                status=MutationStatus.PENDING.value,
                lease_owner=lease_owner,
                lease_acquired_at=db_now,
                last_heartbeat_at=db_now,
                lease_expires_at=db_now + timedelta(seconds=lease_seconds),
                created_at=db_now,
                updated_at=db_now,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raced_row = session.exec(
                    select(CliMutationLedger).where(
                        CliMutationLedger.command == command,
                        CliMutationLedger.idempotency_key == idempotency_key,
                    )
                ).first()
                if raced_row is None:
                    raise
                return self._existing_result(
                    session=session,
                    row=raced_row,
                    request_hash=request_hash,
                    now=now,
                )
            session.refresh(row)
            return LedgerLoadResult(ledger=row)

    def _existing_result(
        self,
        *,
        session: Session,
        row: CliMutationLedger,
        request_hash: str,
        now: datetime,
    ) -> LedgerLoadResult:
        if row.request_hash != request_hash:
            return LedgerLoadResult(ledger=row, error_code=IDEMPOTENCY_KEY_REUSED)
        if row.status == MutationStatus.SUCCEEDED.value:
            response = _json_load(row.response_json)
            return LedgerLoadResult(
                ledger=row,
                replayed=True,
                response=response if isinstance(response, dict) else None,
            )
        if row.status == MutationStatus.PENDING.value:
            return self._handle_pending_existing(session=session, row=row, now=now)
        if row.status == MutationStatus.RECOVERY_REQUIRED.value:
            return LedgerLoadResult(ledger=row, error_code=MUTATION_RECOVERY_REQUIRED)
        return LedgerLoadResult(ledger=row, replayed=True)

    def _handle_pending_existing(
        self,
        *,
        session: Session,
        row: CliMutationLedger,
        now: datetime,
    ) -> LedgerLoadResult:
        db_now = _db_datetime(now)
        if row.lease_expires_at and row.lease_expires_at > db_now:
            return LedgerLoadResult(ledger=row, error_code=MUTATION_IN_PROGRESS)

        statement = (
            update(CliMutationLedger)
            .where(CliMutationLedger.mutation_event_id == row.mutation_event_id)
            .where(CliMutationLedger.status == MutationStatus.PENDING.value)
        )
        if row.lease_owner is None:
            statement = statement.where(CliMutationLedger.lease_owner.is_(None))
        else:
            statement = statement.where(
                CliMutationLedger.lease_owner == row.lease_owner
            )
        if row.lease_expires_at is None:
            statement = statement.where(CliMutationLedger.lease_expires_at.is_(None))
        else:
            statement = statement.where(CliMutationLedger.lease_expires_at <= db_now)

        result = session.exec(
            statement.values(
                status=MutationStatus.RECOVERY_REQUIRED.value,
                recovery_action=RecoveryAction.RECONCILE_THEN_RESUME.value,
                recovery_safe_to_auto_resume=False,
                lease_owner=None,
                lease_acquired_at=None,
                last_heartbeat_at=None,
                lease_expires_at=None,
                last_error_json=_json_dump(_stale_pending_error(row=row, now=now)),
                updated_at=db_now,
            )
        )
        session.commit()
        if result.rowcount != 1:
            return LedgerLoadResult(ledger=row, error_code=MUTATION_IN_PROGRESS)

        refreshed = session.get(CliMutationLedger, row.mutation_event_id)
        if refreshed is None:
            raise ValueError(f"Mutation event {row.mutation_event_id} not found.")
        return LedgerLoadResult(
            ledger=refreshed,
            error_code=MUTATION_RECOVERY_REQUIRED,
        )

    def transition_status(
        self,
        *,
        mutation_event_id: int,
        expected_status: MutationStatus,
        expected_lease_owner: str | None,
        new_status: MutationStatus,
        new_lease_owner: str | None,
        now: datetime,
        lease_seconds: int | None = None,
    ) -> LedgerLoadResult:
        """Transition status using compare-and-set and affected-row checking."""
        db_now = _db_datetime(now)
        with Session(self._engine) as session:
            statement = (
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == mutation_event_id)
                .where(CliMutationLedger.status == expected_status.value)
            )
            if expected_lease_owner is None:
                statement = statement.where(CliMutationLedger.lease_owner.is_(None))
            else:
                statement = statement.where(
                    CliMutationLedger.lease_owner == expected_lease_owner
                )

            values: dict[str, Any] = {
                "status": new_status.value,
                "lease_owner": new_lease_owner,
                "updated_at": db_now,
            }
            if new_lease_owner is None:
                values.update(
                    {
                        "lease_acquired_at": None,
                        "last_heartbeat_at": None,
                        "lease_expires_at": None,
                    }
                )
            elif lease_seconds is not None:
                values.update(
                    {
                        "lease_acquired_at": db_now,
                        "last_heartbeat_at": db_now,
                        "lease_expires_at": db_now + timedelta(seconds=lease_seconds),
                    }
                )

            result = session.exec(statement.values(**values))
            session.commit()
            row = session.get(CliMutationLedger, mutation_event_id)
            if row is None:
                raise ValueError(f"Mutation event {mutation_event_id} not found.")
            if result.rowcount != 1:
                return LedgerLoadResult(
                    ledger=row,
                    error_code=MUTATION_RESUME_CONFLICT,
                )
            return LedgerLoadResult(ledger=row)

    def heartbeat(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        now: datetime,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        """Refresh a lease only when the caller still owns it."""
        db_now = _db_datetime(now)
        with Session(self._engine) as session:
            result = session.exec(
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == mutation_event_id)
                .where(CliMutationLedger.status == MutationStatus.PENDING.value)
                .where(CliMutationLedger.lease_owner == lease_owner)
                .where(CliMutationLedger.lease_expires_at > db_now)
                .values(
                    last_heartbeat_at=db_now,
                    lease_expires_at=db_now + timedelta(seconds=lease_seconds),
                    updated_at=db_now,
                )
            )
            session.commit()
            return result.rowcount == 1

    def require_active_owner(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        now: datetime,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        """Verify ownership immediately before a declared side-effect write."""
        return self.heartbeat(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=lease_seconds,
        )

    def mark_step_complete(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        step: str,
        next_step: str,
        now: datetime,
    ) -> bool:
        """Record a completed step with owner fencing."""
        db_now = _db_datetime(now)
        with Session(self._engine) as session:
            row = session.get(CliMutationLedger, mutation_event_id)
            if (
                row is None
                or row.status != MutationStatus.PENDING.value
                or row.lease_owner != lease_owner
                or row.lease_expires_at is None
                or row.lease_expires_at <= db_now
            ):
                return False

            steps = _completed_steps(row)
            if step not in steps:
                steps.append(step)
            result = session.exec(
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == mutation_event_id)
                .where(CliMutationLedger.status == MutationStatus.PENDING.value)
                .where(CliMutationLedger.lease_owner == lease_owner)
                .where(CliMutationLedger.lease_expires_at > db_now)
                .values(
                    completed_steps_json=_json_dump(steps),
                    current_step=next_step,
                    updated_at=db_now,
                )
            )
            session.commit()
            return result.rowcount == 1

    def finalize_success(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        after: dict[str, Any],
        response: dict[str, Any],
        now: datetime,
    ) -> bool:
        """Store final response when the caller still owns a pending lease."""
        db_now = _db_datetime(now)
        with Session(self._engine) as session:
            result = session.exec(
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == mutation_event_id)
                .where(CliMutationLedger.status == MutationStatus.PENDING.value)
                .where(CliMutationLedger.lease_owner == lease_owner)
                .where(CliMutationLedger.lease_expires_at > db_now)
                .values(
                    status=MutationStatus.SUCCEEDED.value,
                    after_json=_json_dump(after),
                    response_json=_json_dump(response),
                    recovery_action=RecoveryAction.NONE.value,
                    recovery_safe_to_auto_resume=False,
                    lease_owner=None,
                    lease_acquired_at=None,
                    last_heartbeat_at=None,
                    lease_expires_at=None,
                    updated_at=db_now,
                )
            )
            session.commit()
            return result.rowcount == 1

    def _force_recovery_required_for_test(
        self,
        *,
        mutation_event_id: int,
        recovery_action: RecoveryAction,
        safe_to_auto_resume: bool,
        last_error: dict[str, Any],
        now: datetime,
    ) -> None:
        """Force a pending row into recovery-required state for tests."""
        db_now = _db_datetime(now)
        with Session(self._engine) as session:
            result = session.exec(
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == mutation_event_id)
                .where(CliMutationLedger.status == MutationStatus.PENDING.value)
                .values(
                    status=MutationStatus.RECOVERY_REQUIRED.value,
                    recovery_action=recovery_action.value,
                    recovery_safe_to_auto_resume=safe_to_auto_resume,
                    last_error_json=_json_dump(last_error),
                    lease_owner=None,
                    lease_acquired_at=None,
                    last_heartbeat_at=None,
                    lease_expires_at=None,
                    updated_at=db_now,
                )
            )
            session.commit()
            if result.rowcount != 1:
                row = session.get(CliMutationLedger, mutation_event_id)
                if row is None:
                    raise ValueError(f"Mutation event {mutation_event_id} not found.")
                raise RuntimeError(
                    f"Mutation event {mutation_event_id} was not pending."
                )

    def acquire_resume_lease(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        now: datetime,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> LedgerLoadResult:
        """Acquire a recovery lease by compare-and-set."""
        return self.transition_status(
            mutation_event_id=mutation_event_id,
            expected_status=MutationStatus.RECOVERY_REQUIRED,
            expected_lease_owner=None,
            new_status=MutationStatus.PENDING,
            new_lease_owner=lease_owner,
            now=now,
            lease_seconds=lease_seconds,
        )


def _success_result(data: dict[str, Any]) -> dict[str, Any]:
    """Return a standard successful service envelope."""
    return {"ok": True, "data": data, "warnings": [], "errors": []}


def _error_result(
    *,
    code: ErrorCode | str,
    details: dict[str, Any],
    remediation: list[str],
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a standard failed service envelope using registered errors."""
    return {
        "ok": False,
        "data": data,
        "warnings": [],
        "errors": [
            workbench_error(
                code,
                details=details,
                remediation=remediation,
            ).to_dict()
        ],
    }


def _resume_lease_owner(correlation_id: str | None) -> str:
    """Return the deterministic CLI lease owner for recovery acquisition."""
    if correlation_id:
        return f"{DEFAULT_CLI_RESUME_LEASE_OWNER}:{correlation_id}"
    return DEFAULT_CLI_RESUME_LEASE_OWNER


def _timestamp_payload(value: datetime | None) -> str | None:
    """Return a JSON timestamp for a stored DB datetime."""
    if value is None:
        return None
    return _utc_isoformat(value)


def _row_payload(row: CliMutationLedger) -> dict[str, Any]:
    """Return a JSON-friendly mutation ledger row payload."""
    return {
        "mutation_event_id": row.mutation_event_id,
        "command": row.command,
        "idempotency_key": row.idempotency_key,
        "request_hash": row.request_hash,
        "project_id": row.project_id,
        "correlation_id": row.correlation_id,
        "changed_by": row.changed_by,
        "status": row.status,
        "current_step": row.current_step,
        "completed_steps": _completed_steps(row),
        "guard_inputs": _json_blob(row.guard_inputs_json),
        "before": _json_blob(row.before_json),
        "after": _json_blob(row.after_json),
        "response": _json_blob(row.response_json),
        "recovery_action": row.recovery_action,
        "recovery_safe_to_auto_resume": row.recovery_safe_to_auto_resume,
        "lease_owner": row.lease_owner,
        "lease_acquired_at": _timestamp_payload(row.lease_acquired_at),
        "last_heartbeat_at": _timestamp_payload(row.last_heartbeat_at),
        "lease_expires_at": _timestamp_payload(row.lease_expires_at),
        "created_at": _timestamp_payload(row.created_at),
        "updated_at": _timestamp_payload(row.updated_at),
        "last_error": _json_blob(row.last_error_json),
    }
