# CLI Contract Hardening Phase 2A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the mutation-safe CLI contract foundation before shipping real domain mutations such as `project create`.

**Architecture:** Add focused `services.agent_workbench` modules for error codes, version metadata, command schemas, mutation ledger transitions, diagnostics, and a fake mutation harness. Keep `cli/main.py` as a thin transport and keep real project/workflow mutation commands out of this phase. Persist the mutation ledger in the business database, with lease-based fencing and deterministic replay/recovery semantics.

**Tech Stack:** Python 3.12+, SQLModel, SQLite, argparse, Pydantic v2, pytest, existing `services.agent_workbench` facade and envelope patterns.

---

## Phase 2A Contract Invariants

- The ledger is a state machine, not an audit table with loose statuses. Every status transition must be expressed as a compare-and-set using `mutation_event_id`, `expected_status`, `expected_lease_owner`, `new_status`, `new_lease_owner`, and an affected-row count of exactly `1`.
- `DEFAULT_STALE_PENDING_TIMEOUT_SECONDS` is `300`. Tests may pass shorter lease values to simulate stale pending rows quickly, but production defaults must be explicit.
- `pending` means a process owns the ledger lease. A worker must refresh the lease and verify ownership immediately before each declared side-effect write. If ownership verification fails, the worker must stop before the side effect.
- `mutation show` and `mutation list` are read-only operations. `mutation resume` is mutating, accepts only `mutation_event_id` and tracing fields, uses the original request hash and idempotency key, and never accepts arguments that alter the original mutation.
- `last_error` is structured JSON with `code`, `message`, `details`, `retryable`, and `recorded_at`. Free-text-only errors are not acceptable in the ledger.
- The fake mutation harness must simulate two declared side-effect boundaries: `business_marker` and `session_marker`. It must cover success, replay, stale pending, recovery lease acquisition, recovery completion, and duplicate resume fencing.

---

## File Structure

Create:

- `models/agent_workbench.py`: SQLModel table for the CLI mutation ledger.
- `services/agent_workbench/error_codes.py`: central error registry and stable exit code metadata.
- `services/agent_workbench/version.py`: CLI, command, package, and storage schema version helpers.
- `services/agent_workbench/contract_models.py`: Pydantic request/response contract models used by command schemas and mutation harness.
- `services/agent_workbench/mutation_ledger.py`: ledger repository, lease acquisition, compare-and-set transitions, replay, and recovery inspection.
- `services/agent_workbench/diagnostics.py`: `doctor` and `schema check` services.
- `services/agent_workbench/command_schema.py`: command schema/capabilities payload builder.
- `services/agent_workbench/fake_mutation.py`: test harness mutation with two simulated side-effect boundaries.
- `tests/test_agent_workbench_error_codes.py`
- `tests/test_agent_workbench_version.py`
- `tests/test_agent_workbench_mutation_ledger.py`
- `tests/test_agent_workbench_diagnostics.py`
- `tests/test_agent_workbench_command_schema.py`
- `tests/test_agent_workbench_fake_mutation.py`

Modify:

- `models/__init__.py`: expose `agent_workbench` lazily.
- `models/db.py`: import the ledger model before `SQLModel.metadata.create_all()`.
- `db/migrations.py`: create schema-version and mutation-ledger tables idempotently.
- `services/agent_workbench/envelope.py`: enrich `meta`.
- `services/agent_workbench/command_registry.py`: add command versions, stability, mutation flags, and schema metadata.
- `services/agent_workbench/application.py`: add `doctor`, `schema_check`, `capabilities`, `command_schema`, `mutation_show`, `mutation_list`, and `mutation_resume`.
- `cli/main.py`: add read-only contract commands and mutating `mutation resume` transport.
- `tests/test_agent_workbench_envelope.py`
- `tests/test_agent_workbench_cli.py`
- `tests/test_agent_workbench_phase1_integration.py`
- `tests/test_agent_workbench_schema_readiness.py`

---

### Task 1: Mutation Ledger State Machine First

**Files:**
- Create: `models/agent_workbench.py`
- Create: `services/agent_workbench/mutation_ledger.py`
- Modify: `models/__init__.py`
- Modify: `models/db.py`
- Modify: `db/migrations.py`
- Test: `tests/test_agent_workbench_mutation_ledger.py`

- [ ] **Step 1: Write failing ledger model and transition tests**

Add `tests/test_agent_workbench_mutation_ledger.py`:

```python
"""Tests for CLI mutation ledger state transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from models.agent_workbench import CliMutationLedger
from services.agent_workbench.mutation_ledger import (
    IDEMPOTENCY_KEY_REUSED,
    MUTATION_IN_PROGRESS,
    MUTATION_RECOVERY_REQUIRED,
    MUTATION_RESUME_CONFLICT,
    MutationLedgerRepository,
    MutationStatus,
    RecoveryAction,
)


def _repo(engine: Engine) -> MutationLedgerRepository:
    SQLModel.metadata.create_all(engine)
    return MutationLedgerRepository(engine=engine)


def test_create_pending_row_records_request_hash_and_lease(engine: Engine) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    row = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now,
        lease_seconds=30,
    )

    assert row.replayed is False
    assert row.ledger.status == MutationStatus.PENDING.value
    assert row.ledger.lease_owner == "worker-1"
    assert row.ledger.lease_expires_at == now + timedelta(seconds=30)
    assert row.ledger.current_step == "start"


def test_same_key_same_request_replays_success(engine: Engine) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    row = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now,
        lease_seconds=30,
    ).ledger

    repo.finalize_success(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        after={"step": "done"},
        response={"ok": True, "data": {"result": "done"}},
        now=now,
    )

    replay = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-2",
        changed_by="cli-agent",
        lease_owner="worker-2",
        now=now + timedelta(seconds=1),
        lease_seconds=30,
    )

    assert replay.replayed is True
    assert replay.ledger.status == MutationStatus.SUCCEEDED.value
    assert replay.response == {"ok": True, "data": {"result": "done"}}


def test_same_key_different_request_raises_reuse_error(engine: Engine) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now,
        lease_seconds=30,
    )

    result = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:different",
        project_id=7,
        correlation_id="corr-2",
        changed_by="cli-agent",
        lease_owner="worker-2",
        now=now,
        lease_seconds=30,
    )

    assert result.error_code == IDEMPOTENCY_KEY_REUSED


def test_fresh_pending_row_reports_in_progress(engine: Engine) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now,
        lease_seconds=30,
    )

    result = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-2",
        changed_by="cli-agent",
        lease_owner="worker-2",
        now=now + timedelta(seconds=5),
        lease_seconds=30,
    )

    assert result.error_code == MUTATION_IN_PROGRESS


def test_stale_pending_becomes_recovery_required(engine: Engine) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    row = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now,
        lease_seconds=30,
    ).ledger
    repo.mark_step_complete(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        step="business_marker",
        next_step="session_marker",
        now=now + timedelta(seconds=1),
    )

    result = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-2",
        changed_by="cli-agent",
        lease_owner="worker-2",
        now=now + timedelta(seconds=45),
        lease_seconds=30,
    )

    assert result.error_code == MUTATION_RECOVERY_REQUIRED
    with Session(engine) as session:
        stored = session.exec(select(CliMutationLedger)).one()
    assert stored.status == MutationStatus.RECOVERY_REQUIRED.value
    assert stored.recovery_action == RecoveryAction.RECONCILE_THEN_RESUME.value


def test_resume_requires_compare_and_set_from_recovery_required(engine: Engine) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    row = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now,
        lease_seconds=1,
    ).ledger
    repo.force_recovery_required(
        mutation_event_id=row.mutation_event_id,
        recovery_action=RecoveryAction.RESUME_FROM_STEP,
        safe_to_auto_resume=True,
        last_error={
            "code": "CRASHED",
            "message": "Simulated crash.",
            "details": {},
            "retryable": True,
            "recorded_at": now.isoformat(),
        },
        now=now,
    )

    acquired = repo.acquire_resume_lease(
        mutation_event_id=row.mutation_event_id,
        lease_owner="resume-1",
        now=now + timedelta(seconds=2),
        lease_seconds=30,
    )
    conflicted = repo.acquire_resume_lease(
        mutation_event_id=row.mutation_event_id,
        lease_owner="resume-2",
        now=now + timedelta(seconds=3),
        lease_seconds=30,
    )

    assert acquired.error_code is None
    assert acquired.ledger.status == MutationStatus.PENDING.value
    assert acquired.ledger.lease_owner == "resume-1"
    assert conflicted.error_code == MUTATION_RESUME_CONFLICT
```

- [ ] **Step 2: Run ledger tests and verify they fail**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_mutation_ledger.py -q
```

Expected: FAIL with import errors for `models.agent_workbench` and `services.agent_workbench.mutation_ledger`.

- [ ] **Step 3: Add the ledger SQLModel**

Create `models/agent_workbench.py`:

```python
"""Agent workbench persistence models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.types import Text
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


class CliMutationLedger(SQLModel, table=True):
    """Durable mutation ledger for CLI idempotency, audit, and recovery."""

    __tablename__ = "cli_mutation_ledger"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "command",
            "idempotency_key",
            name="uq_cli_mutation_command_idempotency",
        ),
    )

    mutation_event_id: int | None = Field(default=None, primary_key=True)
    command: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    request_hash: str = Field(index=True)
    project_id: int | None = Field(default=None, index=True)
    correlation_id: str = Field(index=True)
    changed_by: str = Field(default="cli-agent", index=True)
    status: str = Field(index=True)
    current_step: str = Field(default="start")
    completed_steps_json: str = Field(default="[]", sa_type=Text)
    guard_inputs_json: str = Field(default="{}", sa_type=Text)
    before_json: str = Field(default="{}", sa_type=Text)
    after_json: str | None = Field(default=None, sa_type=Text)
    response_json: str | None = Field(default=None, sa_type=Text)
    recovery_action: str = Field(default="none", index=True)
    recovery_safe_to_auto_resume: bool = Field(default=False)
    lease_owner: str | None = Field(default=None, index=True)
    lease_acquired_at: datetime | None = Field(default=None)
    last_heartbeat_at: datetime | None = Field(default=None)
    lease_expires_at: datetime | None = Field(default=None)
    last_error_json: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(default_factory=_utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=_utc_now, nullable=False)
```

Modify `models/__init__.py` so `__all__` includes `agent_workbench`:

```python
__all__ = ["agent_workbench", "core", "db", "enums", "events", "specs"]
```

Modify `models/db.py` near the imports to register metadata before `create_all()`:

```python
from models import agent_workbench as _agent_workbench_models  # noqa: F401
```

- [ ] **Step 4: Add migration support for ledger and schema version**

Modify `db/migrations.py` by adding constants and migration functions before `ensure_schema_current`:

```python
AGENT_WORKBENCH_STORAGE_SCHEMA_VERSION = "1"


def migrate_agent_workbench_contract_tables(engine: Engine) -> list[str]:
    """Ensure CLI contract hardening tables exist."""
    actions: list[str] = []
    created_versions = _ensure_table_exists(
        engine,
        "agent_workbench_schema_versions",
        """
        CREATE TABLE agent_workbench_schema_versions (
            component TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    if created_versions:
        actions.append("created table: agent_workbench_schema_versions")

    created_ledger = _ensure_table_exists(
        engine,
        "cli_mutation_ledger",
        """
        CREATE TABLE cli_mutation_ledger (
            mutation_event_id INTEGER PRIMARY KEY,
            command VARCHAR NOT NULL,
            idempotency_key VARCHAR NOT NULL,
            request_hash VARCHAR NOT NULL,
            project_id INTEGER,
            correlation_id VARCHAR NOT NULL,
            changed_by VARCHAR NOT NULL DEFAULT 'cli-agent',
            status VARCHAR NOT NULL,
            current_step VARCHAR NOT NULL DEFAULT 'start',
            completed_steps_json TEXT NOT NULL DEFAULT '[]',
            guard_inputs_json TEXT NOT NULL DEFAULT '{}',
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT,
            response_json TEXT,
            recovery_action VARCHAR NOT NULL DEFAULT 'none',
            recovery_safe_to_auto_resume BOOLEAN NOT NULL DEFAULT 0,
            lease_owner VARCHAR,
            lease_acquired_at TIMESTAMP,
            last_heartbeat_at TIMESTAMP,
            lease_expires_at TIMESTAMP,
            last_error_json TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_cli_mutation_command_idempotency
                UNIQUE (command, idempotency_key)
        )
        """,
    )
    if created_ledger:
        actions.append("created table: cli_mutation_ledger")

    for index_name, columns in {
        "ix_cli_mutation_ledger_status": ["status"],
        "ix_cli_mutation_ledger_project_id": ["project_id"],
        "ix_cli_mutation_ledger_request_hash": ["request_hash"],
        "ix_cli_mutation_ledger_lease_owner": ["lease_owner"],
    }.items():
        if _ensure_index_exists(engine, "cli_mutation_ledger", index_name, columns):
            actions.append(f"created index: {index_name}")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO agent_workbench_schema_versions(component, version)
                VALUES ('agent_workbench', :version)
                ON CONFLICT(component) DO UPDATE SET
                    version = excluded.version,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {"version": AGENT_WORKBENCH_STORAGE_SCHEMA_VERSION},
        )
    return actions
```

Then call it in `ensure_schema_current` after task execution logs and before performance indexes:

```python
actions.extend(migrate_agent_workbench_contract_tables(engine))
```

- [ ] **Step 5: Add ledger repository and transition helpers**

Create `services/agent_workbench/mutation_ledger.py`:

```python
"""Durable mutation ledger for CLI idempotency and recovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from models.agent_workbench import CliMutationLedger

IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
MUTATION_IN_PROGRESS = "MUTATION_IN_PROGRESS"
MUTATION_RECOVERY_REQUIRED = "MUTATION_RECOVERY_REQUIRED"
MUTATION_RESUME_CONFLICT = "MUTATION_RESUME_CONFLICT"
DEFAULT_STALE_PENDING_TIMEOUT_SECONDS = 300
DEFAULT_LEASE_SECONDS = DEFAULT_STALE_PENDING_TIMEOUT_SECONDS


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
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_load(value: str | None) -> dict[str, Any] | list[Any] | None:
    if not value:
        return None
    loaded = json.loads(value)
    if isinstance(loaded, (dict, list)):
        return loaded
    return None


def _completed_steps(row: CliMutationLedger) -> list[str]:
    loaded = _json_load(row.completed_steps_json)
    if isinstance(loaded, list):
        return [str(item) for item in loaded]
    return []


class MutationLedgerRepository:
    """Repository for mutation ledger compare-and-set transitions."""

    def __init__(self, *, engine: Engine) -> None:
        self._engine = engine

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
                lease_acquired_at=now,
                last_heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
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
            if row.lease_expires_at and row.lease_expires_at > now:
                return LedgerLoadResult(ledger=row, error_code=MUTATION_IN_PROGRESS)
            statement = (
                update(CliMutationLedger)
                .where(
                    CliMutationLedger.mutation_event_id
                    == row.mutation_event_id
                )
                .where(CliMutationLedger.status == MutationStatus.PENDING.value)
                .where(CliMutationLedger.lease_owner == row.lease_owner)
                .values(
                    status=MutationStatus.RECOVERY_REQUIRED.value,
                    recovery_action=RecoveryAction.RECONCILE_THEN_RESUME.value,
                    recovery_safe_to_auto_resume=False,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_json=_json_dump(
                        {
                            "code": "STALE_PENDING",
                            "message": "Pending mutation lease expired.",
                            "details": {"current_step": row.current_step},
                            "retryable": True,
                            "recorded_at": now.isoformat(),
                        }
                    ),
                    updated_at=now,
                )
            )
            result = session.exec(statement)
            session.commit()
            if result.rowcount != 1:
                return LedgerLoadResult(ledger=row, error_code=MUTATION_IN_PROGRESS)
            session.refresh(row)
            return LedgerLoadResult(ledger=row, error_code=MUTATION_RECOVERY_REQUIRED)
        if row.status == MutationStatus.RECOVERY_REQUIRED.value:
            return LedgerLoadResult(ledger=row, error_code=MUTATION_RECOVERY_REQUIRED)
        return LedgerLoadResult(ledger=row, replayed=True)

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
        """Transition status using a compare-and-set and affected-row check."""
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
                "updated_at": now,
            }
            if new_lease_owner is not None and lease_seconds is not None:
                values.update(
                    {
                        "lease_acquired_at": now,
                        "last_heartbeat_at": now,
                        "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    }
                )
            if new_lease_owner is None:
                values["lease_expires_at"] = None
            result = session.exec(statement.values(**values))
            session.commit()
            row = session.get(CliMutationLedger, mutation_event_id)
            if row is None:
                raise ValueError(f"Mutation event {mutation_event_id} not found.")
            if result.rowcount != 1:
                return LedgerLoadResult(row, error_code=MUTATION_RESUME_CONFLICT)
            return LedgerLoadResult(row)

    def heartbeat(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        now: datetime,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        """Refresh a lease only when the caller still owns it."""
        with Session(self._engine) as session:
            statement = (
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == mutation_event_id)
                .where(CliMutationLedger.lease_owner == lease_owner)
                .values(
                    last_heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    updated_at=now,
                )
            )
            result = session.exec(statement)
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
        with Session(self._engine) as session:
            row = session.get(CliMutationLedger, mutation_event_id)
            if row is None or row.lease_owner != lease_owner:
                return False
            steps = _completed_steps(row)
            if step not in steps:
                steps.append(step)
            row.completed_steps_json = _json_dump(steps)
            row.current_step = next_step
            row.updated_at = now
            session.add(row)
            session.commit()
            return True

    def finalize_success(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        after: dict[str, Any],
        response: dict[str, Any],
        now: datetime,
    ) -> bool:
        """Store final response when the caller still owns the lease."""
        with Session(self._engine) as session:
            statement = (
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == mutation_event_id)
                .where(CliMutationLedger.status == MutationStatus.PENDING.value)
                .where(CliMutationLedger.lease_owner == lease_owner)
                .values(
                    status=MutationStatus.SUCCEEDED.value,
                    after_json=_json_dump(after),
                    response_json=_json_dump(response),
                    recovery_action=RecoveryAction.NONE.value,
                    recovery_safe_to_auto_resume=False,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            result = session.exec(statement)
            session.commit()
            return result.rowcount == 1

    def force_recovery_required(
        self,
        *,
        mutation_event_id: int,
        recovery_action: RecoveryAction,
        safe_to_auto_resume: bool,
        last_error: dict[str, Any],
        now: datetime,
    ) -> None:
        """Force a row into recovery-required state for tests only."""
        with Session(self._engine) as session:
            row = session.get(CliMutationLedger, mutation_event_id)
            if row is None:
                raise ValueError(f"Mutation event {mutation_event_id} not found.")
            row.status = MutationStatus.RECOVERY_REQUIRED.value
            row.recovery_action = recovery_action.value
            row.recovery_safe_to_auto_resume = safe_to_auto_resume
            row.last_error_json = _json_dump(last_error)
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = now
            session.add(row)
            session.commit()

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
```

- [ ] **Step 6: Run ledger tests and commit**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_mutation_ledger.py -q
```

Expected: PASS.

Commit:

```bash
git add models/agent_workbench.py models/__init__.py models/db.py db/migrations.py services/agent_workbench/mutation_ledger.py tests/test_agent_workbench_mutation_ledger.py
git commit -m "feat: add CLI mutation ledger"
```

---

### Task 2: Error Registry, Version Metadata, And Envelope Enrichment

**Files:**
- Create: `services/agent_workbench/error_codes.py`
- Create: `services/agent_workbench/version.py`
- Modify: `services/agent_workbench/envelope.py`
- Test: `tests/test_agent_workbench_error_codes.py`
- Test: `tests/test_agent_workbench_version.py`
- Test: `tests/test_agent_workbench_envelope.py`

- [ ] **Step 1: Write failing error/version/envelope tests**

Add `tests/test_agent_workbench_error_codes.py`:

```python
"""Tests for stable CLI error code registry."""

from services.agent_workbench.error_codes import (
    ErrorCode,
    error_metadata,
    registered_error_codes,
    workbench_error,
)


def test_registry_contains_mutation_recovery_codes() -> None:
    codes = registered_error_codes()
    assert ErrorCode.MUTATION_IN_PROGRESS.value in codes
    assert ErrorCode.MUTATION_RESUME_CONFLICT.value in codes
    assert ErrorCode.STALE_CONTEXT_FINGERPRINT.value in codes


def test_workbench_error_uses_registered_exit_code() -> None:
    error = workbench_error(
        ErrorCode.MUTATION_IN_PROGRESS,
        message="Mutation is still running.",
        details={"mutation_event_id": 101},
        remediation=["Retry after the active lease expires."],
    )

    metadata = error_metadata(ErrorCode.MUTATION_IN_PROGRESS)
    assert error.code == "MUTATION_IN_PROGRESS"
    assert error.exit_code == metadata.default_exit_code
    assert error.retryable is True
```

Add `tests/test_agent_workbench_version.py`:

```python
"""Tests for workbench version metadata."""

from services.agent_workbench.version import (
    COMMAND_VERSION,
    STORAGE_SCHEMA_VERSION,
    agileforge_version,
)


def test_version_metadata_is_stable_strings() -> None:
    assert COMMAND_VERSION == "1"
    assert STORAGE_SCHEMA_VERSION == "1"
    assert agileforge_version()
```

Extend `tests/test_agent_workbench_envelope.py` with:

```python
def test_success_envelope_meta_has_contract_fields() -> None:
    envelope = success_envelope(
        command="agileforge project list",
        data={"items": []},
        correlation_id="corr-1",
    )

    meta = envelope["meta"]
    assert meta["schema_version"] == "agileforge.cli.v1"
    assert meta["command"] == "agileforge project list"
    assert meta["command_version"] == "1"
    assert meta["agileforge_version"]
    assert meta["storage_schema_version"] == "1"
    assert meta["correlation_id"] == "corr-1"
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_error_codes.py tests/test_agent_workbench_version.py tests/test_agent_workbench_envelope.py -q
```

Expected: FAIL for missing modules and missing envelope fields.

- [ ] **Step 3: Add error registry**

Create `services/agent_workbench/error_codes.py`:

```python
"""Stable error code registry for agent workbench commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from services.agent_workbench.envelope import WorkbenchError


class ErrorCode(StrEnum):
    """Stable machine-readable CLI error codes."""

    INVALID_COMMAND = "INVALID_COMMAND"
    COMMAND_EXCEPTION = "COMMAND_EXCEPTION"
    COMMAND_NOT_IMPLEMENTED = "COMMAND_NOT_IMPLEMENTED"
    SCHEMA_NOT_READY = "SCHEMA_NOT_READY"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    AUTHORITY_NOT_ACCEPTED = "AUTHORITY_NOT_ACCEPTED"
    STALE_STATE = "STALE_STATE"
    STALE_ARTIFACT_FINGERPRINT = "STALE_ARTIFACT_FINGERPRINT"
    STALE_CONTEXT_FINGERPRINT = "STALE_CONTEXT_FINGERPRINT"
    STALE_AUTHORITY_VERSION = "STALE_AUTHORITY_VERSION"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    MUTATION_RECOVERY_REQUIRED = "MUTATION_RECOVERY_REQUIRED"
    MUTATION_IN_PROGRESS = "MUTATION_IN_PROGRESS"
    MUTATION_RESUME_CONFLICT = "MUTATION_RESUME_CONFLICT"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    ACTIVE_STATE_BLOCKS_DELETE = "ACTIVE_STATE_BLOCKS_DELETE"
    MUTATION_FAILED = "MUTATION_FAILED"
    MUTATION_ROLLBACK = "MUTATION_ROLLBACK"


@dataclass(frozen=True)
class ErrorMetadata:
    """Registry metadata for one error code."""

    code: ErrorCode
    default_exit_code: int
    retryable: bool
    description: str


_REGISTRY: dict[ErrorCode, ErrorMetadata] = {
    ErrorCode.INVALID_COMMAND: ErrorMetadata(ErrorCode.INVALID_COMMAND, 2, False, "Invalid command usage."),
    ErrorCode.COMMAND_EXCEPTION: ErrorMetadata(ErrorCode.COMMAND_EXCEPTION, 1, False, "Unexpected command exception."),
    ErrorCode.COMMAND_NOT_IMPLEMENTED: ErrorMetadata(ErrorCode.COMMAND_NOT_IMPLEMENTED, 2, False, "Command is registered but not implemented."),
    ErrorCode.SCHEMA_NOT_READY: ErrorMetadata(ErrorCode.SCHEMA_NOT_READY, 5, True, "Required schema objects are missing."),
    ErrorCode.SCHEMA_VERSION_MISMATCH: ErrorMetadata(ErrorCode.SCHEMA_VERSION_MISMATCH, 5, True, "Storage schema version is incompatible."),
    ErrorCode.PROJECT_NOT_FOUND: ErrorMetadata(ErrorCode.PROJECT_NOT_FOUND, 4, False, "Project lookup failed."),
    ErrorCode.AUTHORITY_NOT_ACCEPTED: ErrorMetadata(ErrorCode.AUTHORITY_NOT_ACCEPTED, 4, False, "No accepted authority is available."),
    ErrorCode.STALE_STATE: ErrorMetadata(ErrorCode.STALE_STATE, 3, True, "Expected workflow state did not match."),
    ErrorCode.STALE_ARTIFACT_FINGERPRINT: ErrorMetadata(ErrorCode.STALE_ARTIFACT_FINGERPRINT, 3, True, "Reviewed artifact fingerprint changed."),
    ErrorCode.STALE_CONTEXT_FINGERPRINT: ErrorMetadata(ErrorCode.STALE_CONTEXT_FINGERPRINT, 3, True, "Reviewed context fingerprint changed."),
    ErrorCode.STALE_AUTHORITY_VERSION: ErrorMetadata(ErrorCode.STALE_AUTHORITY_VERSION, 3, True, "Accepted authority version changed."),
    ErrorCode.IDEMPOTENCY_KEY_REUSED: ErrorMetadata(ErrorCode.IDEMPOTENCY_KEY_REUSED, 2, False, "Idempotency key was reused with a different request."),
    ErrorCode.MUTATION_RECOVERY_REQUIRED: ErrorMetadata(ErrorCode.MUTATION_RECOVERY_REQUIRED, 1, True, "Mutation requires recovery before replay."),
    ErrorCode.MUTATION_IN_PROGRESS: ErrorMetadata(ErrorCode.MUTATION_IN_PROGRESS, 1, True, "Mutation lease is still active."),
    ErrorCode.MUTATION_RESUME_CONFLICT: ErrorMetadata(ErrorCode.MUTATION_RESUME_CONFLICT, 1, True, "Another worker acquired recovery."),
    ErrorCode.CONFIRMATION_REQUIRED: ErrorMetadata(ErrorCode.CONFIRMATION_REQUIRED, 2, False, "Destructive confirmation is missing."),
    ErrorCode.ACTIVE_STATE_BLOCKS_DELETE: ErrorMetadata(ErrorCode.ACTIVE_STATE_BLOCKS_DELETE, 4, False, "Active workflow state blocks deletion."),
    ErrorCode.MUTATION_FAILED: ErrorMetadata(ErrorCode.MUTATION_FAILED, 1, False, "Mutation failed before completion."),
    ErrorCode.MUTATION_ROLLBACK: ErrorMetadata(ErrorCode.MUTATION_ROLLBACK, 1, True, "Mutation rolled back or needs recovery."),
}


def registered_error_codes() -> tuple[str, ...]:
    """Return registered stable error code strings."""
    return tuple(code.value for code in ErrorCode)


def error_metadata(code: ErrorCode) -> ErrorMetadata:
    """Return metadata for one registered error code."""
    return _REGISTRY[code]


def workbench_error(
    code: ErrorCode,
    *,
    message: str,
    details: dict[str, Any] | None = None,
    remediation: list[str] | None = None,
) -> WorkbenchError:
    """Build a WorkbenchError from registry metadata."""
    metadata = error_metadata(code)
    return WorkbenchError(
        code=code.value,
        message=message,
        details=details or {},
        remediation=remediation or [],
        exit_code=metadata.default_exit_code,
        retryable=metadata.retryable,
    )
```

- [ ] **Step 4: Add version helpers and enrich envelopes**

Create `services/agent_workbench/version.py`:

```python
"""Version metadata for CLI contracts."""

from importlib.metadata import PackageNotFoundError, version

COMMAND_VERSION = "1"
STORAGE_SCHEMA_VERSION = "1"


def agileforge_version() -> str:
    """Return installed package version or dev fallback."""
    try:
        return version("agileforge")
    except PackageNotFoundError:
        return "dev"
```

Modify `services/agent_workbench/envelope.py`:

```python
from uuid import uuid4

from services.agent_workbench.version import (
    COMMAND_VERSION,
    STORAGE_SCHEMA_VERSION,
    agileforge_version,
)
```

Change `success_envelope` and `error_envelope` signatures to accept `correlation_id: str | None = None`, and set `meta` like this in both:

```python
"meta": {
    "schema_version": SCHEMA_VERSION,
    "command": command,
    "command_version": COMMAND_VERSION,
    "agileforge_version": agileforge_version(),
    "storage_schema_version": STORAGE_SCHEMA_VERSION,
    "generated_at": generated_at or utc_now_iso(),
    "correlation_id": correlation_id or str(uuid4()),
},
```

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_error_codes.py tests/test_agent_workbench_version.py tests/test_agent_workbench_envelope.py -q
```

Expected: PASS.

Commit:

```bash
git add services/agent_workbench/error_codes.py services/agent_workbench/version.py services/agent_workbench/envelope.py tests/test_agent_workbench_error_codes.py tests/test_agent_workbench_version.py tests/test_agent_workbench_envelope.py
git commit -m "feat: harden CLI envelope contract"
```

---

### Task 3: Command Registry, Capabilities, And Schema Contracts

**Files:**
- Create: `services/agent_workbench/contract_models.py`
- Create: `services/agent_workbench/command_schema.py`
- Modify: `services/agent_workbench/command_registry.py`
- Test: `tests/test_agent_workbench_command_schema.py`

- [ ] **Step 1: Write failing command schema tests**

Add `tests/test_agent_workbench_command_schema.py`:

```python
"""Tests for command capabilities and schema contracts."""

from services.agent_workbench.command_registry import installed_commands
from services.agent_workbench.command_schema import (
    capabilities_payload,
    command_schema_payload,
)


def test_installed_commands_include_contract_metadata() -> None:
    commands = {command.name: command for command in installed_commands()}
    status = commands["agileforge status"]

    assert status.command_version == "1"
    assert status.stable is True
    assert status.mutates is False
    assert status.destructive is False


def test_capabilities_exposes_mutation_resume_as_mutating() -> None:
    payload = capabilities_payload()
    by_name = {item["name"]: item for item in payload["commands"]}

    assert by_name["agileforge mutation show"]["mutates"] is False
    assert by_name["agileforge mutation list"]["mutates"] is False
    assert by_name["agileforge mutation resume"]["mutates"] is True


def test_command_schema_exposes_input_output_and_errors() -> None:
    payload = command_schema_payload("agileforge mutation resume")

    assert payload["name"] == "agileforge mutation resume"
    assert payload["input"]["required"] == ["mutation_event_id"]
    assert "MUTATION_RESUME_CONFLICT" in payload["errors"]
    assert payload["output"]["envelope_schema"]["type"] == "object"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_command_schema.py -q
```

Expected: FAIL for missing metadata and missing `command_schema` module.

- [ ] **Step 3: Add contract models**

Create `services/agent_workbench/contract_models.py`:

```python
"""Pydantic models for CLI command contract documentation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CommandInputSchema(BaseModel):
    """Documented command input schema."""

    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)


class CommandOutputSchema(BaseModel):
    """Documented command output schema."""

    model_config = ConfigDict(extra="forbid")

    data_schema: dict[str, Any] = Field(default_factory=dict)
    envelope_schema: dict[str, Any] = Field(default_factory=dict)


class CommandContractSchema(BaseModel):
    """Full input/output contract for one command."""

    model_config = ConfigDict(extra="forbid")

    name: str
    command_version: str
    stable: bool
    mutates: bool
    destructive: bool
    input: CommandInputSchema
    output: CommandOutputSchema
    guard_policy: list[str] = Field(default_factory=list)
    idempotency_required: bool = False
    errors: list[str] = Field(default_factory=list)
    exit_codes: list[int] = Field(default_factory=list)
```

- [ ] **Step 4: Enrich command registry**

Modify `services/agent_workbench/command_registry.py`:

```python
@dataclass(frozen=True)
class CommandMetadata:
    """Metadata for an installed workbench command."""

    name: str
    mutates: bool
    phase: str
    command_version: str = "1"
    stable: bool = True
    destructive: bool = False
    accepts_expected_state: bool = False
    accepts_expected_artifact_fingerprint: bool = False
    accepts_expected_context_fingerprint: bool = False
    accepts_expected_authority_version: bool = False
    requires_idempotency_key: bool = False
    input_required: tuple[str, ...] = ()
    input_optional: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
```

Append Phase 2A operational commands to the installed command tuple:

```python
CommandMetadata(name="agileforge doctor", mutates=False, phase="phase_2a"),
CommandMetadata(name="agileforge schema check", mutates=False, phase="phase_2a"),
CommandMetadata(name="agileforge capabilities", mutates=False, phase="phase_2a"),
CommandMetadata(
    name="agileforge command schema",
    mutates=False,
    phase="phase_2a",
    input_required=("command_name",),
),
CommandMetadata(
    name="agileforge mutation show",
    mutates=False,
    phase="phase_2a",
    input_required=("mutation_event_id",),
),
CommandMetadata(
    name="agileforge mutation list",
    mutates=False,
    phase="phase_2a",
    input_optional=("project_id", "status"),
),
CommandMetadata(
    name="agileforge mutation resume",
    mutates=True,
    phase="phase_2a",
    input_required=("mutation_event_id",),
    input_optional=("correlation_id",),
    errors=("MUTATION_IN_PROGRESS", "MUTATION_RESUME_CONFLICT"),
),
```

- [ ] **Step 5: Add schema/capabilities builder**

Create `services/agent_workbench/command_schema.py`:

```python
"""Command schema and capability payloads."""

from __future__ import annotations

from typing import Any

from services.agent_workbench.command_registry import (
    CommandMetadata,
    installed_commands,
)
from services.agent_workbench.contract_models import (
    CommandContractSchema,
    CommandInputSchema,
    CommandOutputSchema,
)

_ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "data", "warnings", "errors", "meta"],
    "properties": {
        "ok": {"type": "boolean"},
        "data": {"type": ["object", "array", "null"]},
        "warnings": {"type": "array"},
        "errors": {"type": "array"},
        "meta": {"type": "object"},
    },
}


def _metadata_by_name() -> dict[str, CommandMetadata]:
    return {command.name: command for command in installed_commands()}


def capabilities_payload() -> dict[str, Any]:
    """Return installed command capability metadata."""
    return {
        "commands": [
            {
                "name": command.name,
                "phase": command.phase,
                "command_version": command.command_version,
                "stable": command.stable,
                "mutates": command.mutates,
                "destructive": command.destructive,
                "requires_idempotency_key": command.requires_idempotency_key,
            }
            for command in installed_commands()
        ]
    }


def command_schema_payload(command_name: str) -> dict[str, Any]:
    """Return command input/output contract schema."""
    command = _metadata_by_name()[command_name]
    schema = CommandContractSchema(
        name=command.name,
        command_version=command.command_version,
        stable=command.stable,
        mutates=command.mutates,
        destructive=command.destructive,
        input=CommandInputSchema(
            required=list(command.input_required),
            optional=list(command.input_optional),
        ),
        output=CommandOutputSchema(
            data_schema={"type": "object"},
            envelope_schema=_ENVELOPE_SCHEMA,
        ),
        guard_policy=[
            flag
            for enabled, flag in [
                (command.accepts_expected_state, "expected_state"),
                (
                    command.accepts_expected_artifact_fingerprint,
                    "expected_artifact_fingerprint",
                ),
                (
                    command.accepts_expected_context_fingerprint,
                    "expected_context_fingerprint",
                ),
                (
                    command.accepts_expected_authority_version,
                    "expected_authority_version",
                ),
            ]
            if enabled
        ],
        idempotency_required=command.requires_idempotency_key,
        errors=list(command.errors),
        exit_codes=sorted({0, 1, 2, 3, 4, 5}),
    )
    return schema.model_dump(mode="json")
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_command_schema.py -q
```

Expected: PASS.

Commit:

```bash
git add services/agent_workbench/contract_models.py services/agent_workbench/command_schema.py services/agent_workbench/command_registry.py tests/test_agent_workbench_command_schema.py
git commit -m "feat: expose CLI command contracts"
```

---

### Task 4: Diagnostics And Schema Checks

**Files:**
- Create: `services/agent_workbench/diagnostics.py`
- Modify: `services/agent_workbench/application.py`
- Test: `tests/test_agent_workbench_diagnostics.py`

- [ ] **Step 1: Write failing diagnostics tests**

Add `tests/test_agent_workbench_diagnostics.py`:

```python
"""Tests for workbench diagnostics commands."""

from sqlalchemy.engine import Engine

from services.agent_workbench.diagnostics import doctor_payload, schema_check_payload


def test_schema_check_reports_business_and_session_store(engine: Engine) -> None:
    payload = schema_check_payload(business_engine=engine, session_db_url="sqlite:///:memory:")

    assert payload["ok"] is True
    stores = {item["name"]: item for item in payload["stores"]}
    assert stores["business_db"]["ready"] is True
    assert stores["workflow_session_store"]["ready"] is True
    assert stores["workflow_session_store"]["version_source"] == "unavailable"


def test_doctor_reports_cwd_and_repo_root(engine: Engine) -> None:
    payload = doctor_payload(business_engine=engine, session_db_url="sqlite:///:memory:")

    assert payload["ok"] is True
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["business_db"]["status"] == "ok"
    assert checks["central_repo_root"]["status"] == "ok"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_diagnostics.py -q
```

Expected: FAIL for missing module.

- [ ] **Step 3: Add diagnostics implementation**

Create `services/agent_workbench/diagnostics.py`:

```python
"""Operational diagnostics for the agent workbench CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from models.db import get_engine
from services.agent_workbench.version import STORAGE_SCHEMA_VERSION
from utils.runtime_config import get_session_db_target


def _business_store(engine: Engine) -> dict[str, Any]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    version_ready = "agent_workbench_schema_versions" in tables
    ledger_ready = "cli_mutation_ledger" in tables
    return {
        "name": "business_db",
        "ready": version_ready and ledger_ready,
        "required_version": STORAGE_SCHEMA_VERSION,
        "version_source": "agent_workbench_schema_versions",
        "checks": {
            "schema_versions_table": version_ready,
            "mutation_ledger_table": ledger_ready,
        },
    }


def _session_store(session_db_url: str) -> dict[str, Any]:
    ready = session_db_url.startswith("sqlite")
    return {
        "name": "workflow_session_store",
        "ready": ready,
        "required_version": None,
        "version_source": "unavailable",
        "checks": {
            "configured": bool(session_db_url),
            "sqlite_url": session_db_url.startswith("sqlite"),
            "readable_writable_mode": ready,
        },
    }


def schema_check_payload(
    *,
    business_engine: Engine | None = None,
    session_db_url: str | None = None,
) -> dict[str, Any]:
    """Return structured storage compatibility status."""
    engine = business_engine or get_engine()
    session_url = session_db_url or get_session_db_target().sqlite_url
    stores = [_business_store(engine), _session_store(session_url)]
    return {"ok": all(store["ready"] for store in stores), "stores": stores}


def doctor_payload(
    *,
    business_engine: Engine | None = None,
    session_db_url: str | None = None,
) -> dict[str, Any]:
    """Return operational readiness checks for the CLI."""
    schema = schema_check_payload(
        business_engine=business_engine,
        session_db_url=session_db_url,
    )
    repo_root = Path(__file__).resolve().parents[2]
    checks = [
        {"name": "business_db", "status": "ok" if schema["stores"][0]["ready"] else "blocked"},
        {"name": "workflow_session_store", "status": "ok" if schema["stores"][1]["ready"] else "blocked"},
        {"name": "central_repo_root", "status": "ok" if (repo_root / "pyproject.toml").exists() else "blocked"},
        {"name": "caller_cwd", "status": "ok", "path": str(Path.cwd())},
    ]
    return {"ok": all(check["status"] == "ok" for check in checks), "checks": checks}
```

- [ ] **Step 4: Add application facade methods**

Modify `services/agent_workbench/application.py` imports:

```python
from services.agent_workbench.command_schema import (
    capabilities_payload,
    command_schema_payload,
)
from services.agent_workbench.diagnostics import doctor_payload, schema_check_payload
```

Add methods to `AgentWorkbenchApplication`:

```python
    def doctor(self) -> dict[str, Any]:
        """Return operational CLI diagnostics."""
        return {"ok": True, "data": doctor_payload(), "warnings": [], "errors": []}

    def schema_check(self) -> dict[str, Any]:
        """Return storage schema compatibility checks."""
        return {"ok": True, "data": schema_check_payload(), "warnings": [], "errors": []}

    def capabilities(self) -> dict[str, Any]:
        """Return installed CLI capabilities."""
        return {"ok": True, "data": capabilities_payload(), "warnings": [], "errors": []}

    def command_schema(self, *, command_name: str) -> dict[str, Any]:
        """Return a command input/output contract."""
        return {
            "ok": True,
            "data": command_schema_payload(command_name),
            "warnings": [],
            "errors": [],
        }
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_diagnostics.py tests/test_agent_workbench_application.py -q
```

Expected: PASS.

Commit:

```bash
git add services/agent_workbench/diagnostics.py services/agent_workbench/application.py tests/test_agent_workbench_diagnostics.py
git commit -m "feat: add CLI diagnostics facade"
```

---

### Task 5: Fake Mutation Harness

**Files:**
- Create: `services/agent_workbench/fake_mutation.py`
- Test: `tests/test_agent_workbench_fake_mutation.py`

- [ ] **Step 1: Write failing fake mutation tests**

Add `tests/test_agent_workbench_fake_mutation.py`:

```python
"""Tests for the Phase 2A fake mutation harness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from services.agent_workbench.fake_mutation import (
    FakeMutationCrash,
    FakeMutationRunner,
    FakeSideEffectSink,
)
from services.agent_workbench.mutation_ledger import (
    MUTATION_RECOVERY_REQUIRED,
    MUTATION_RESUME_CONFLICT,
    MutationLedgerRepository,
)


def _runner(engine: Engine) -> tuple[FakeMutationRunner, FakeSideEffectSink]:
    SQLModel.metadata.create_all(engine)
    sink = FakeSideEffectSink()
    repo = MutationLedgerRepository(engine=engine)
    return FakeMutationRunner(ledger=repo, side_effects=sink), sink


def test_fake_mutation_runs_two_side_effect_boundaries(engine: Engine) -> None:
    runner, sink = _runner(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    result = runner.run(
        project_id=7,
        idempotency_key="fake-key-001",
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now,
    )

    assert result["ok"] is True
    assert sink.business_markers == [7]
    assert sink.session_markers == [7]


def test_fake_mutation_replays_success_without_rewriting(engine: Engine) -> None:
    runner, sink = _runner(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    first = runner.run(7, "fake-key-001", "corr-1", "cli-agent", "worker-1", now)
    replay = runner.run(
        7,
        "fake-key-001",
        "corr-2",
        "cli-agent",
        "worker-2",
        now + timedelta(seconds=1),
    )

    assert first == replay
    assert sink.business_markers == [7]
    assert sink.session_markers == [7]


def test_fake_mutation_crash_after_first_step_requires_recovery(engine: Engine) -> None:
    runner, sink = _runner(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    try:
        runner.run(
            7,
            "fake-key-001",
            "corr-1",
            "cli-agent",
            "worker-1",
            now,
            crash_after_business_marker=True,
        )
    except FakeMutationCrash:
        pass

    result = runner.run(
        7,
        "fake-key-001",
        "corr-2",
        "cli-agent",
        "worker-2",
        now + timedelta(seconds=45),
    )

    assert result["ok"] is False
    assert result["errors"][0]["code"] == MUTATION_RECOVERY_REQUIRED
    assert sink.business_markers == [7]
    assert sink.session_markers == []


def test_fake_mutation_resume_completes_second_boundary_once(engine: Engine) -> None:
    runner, sink = _runner(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    try:
        runner.run(
            7,
            "fake-key-001",
            "corr-1",
            "cli-agent",
            "worker-1",
            now,
            crash_after_business_marker=True,
        )
    except FakeMutationCrash:
        pass

    stale = runner.run(
        7,
        "fake-key-001",
        "corr-2",
        "cli-agent",
        "worker-2",
        now + timedelta(seconds=45),
    )
    mutation_event_id = stale["errors"][0]["details"]["mutation_event_id"]

    resumed = runner.resume(
        mutation_event_id=mutation_event_id,
        lease_owner="resume-1",
        now=now + timedelta(seconds=46),
    )
    duplicate_resume = runner.resume(
        mutation_event_id=mutation_event_id,
        lease_owner="resume-2",
        now=now + timedelta(seconds=47),
    )

    assert resumed["ok"] is True
    assert duplicate_resume["ok"] is False
    assert duplicate_resume["errors"][0]["code"] == MUTATION_RESUME_CONFLICT
    assert sink.business_markers == [7]
    assert sink.session_markers == [7]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_fake_mutation.py -q
```

Expected: FAIL for missing fake mutation module.

- [ ] **Step 3: Add fake mutation harness**

Create `services/agent_workbench/fake_mutation.py`:

```python
"""Fake mutation harness for proving Phase 2A mutation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from services.agent_workbench.mutation_ledger import (
    MUTATION_RECOVERY_REQUIRED,
    MUTATION_RESUME_CONFLICT,
    MutationLedgerRepository,
)


class FakeMutationCrash(RuntimeError):
    """Raised to simulate a crash after a side-effect boundary."""


@dataclass
class FakeSideEffectSink:
    """In-memory sink simulating two declared side-effect stores."""

    business_markers: list[int] = field(default_factory=list)
    session_markers: list[int] = field(default_factory=list)

    def write_business_marker(self, project_id: int) -> None:
        """Simulate a business DB side effect."""
        self.business_markers.append(project_id)

    def write_session_marker(self, project_id: int) -> None:
        """Simulate a workflow session side effect."""
        self.session_markers.append(project_id)


class FakeMutationRunner:
    """Two-step fake mutation used only by Phase 2A tests."""

    def __init__(
        self,
        *,
        ledger: MutationLedgerRepository,
        side_effects: FakeSideEffectSink,
        lease_seconds: int = 30,
    ) -> None:
        self._ledger = ledger
        self._side_effects = side_effects
        self._lease_seconds = lease_seconds

    def run(
        self,
        project_id: int,
        idempotency_key: str,
        correlation_id: str,
        changed_by: str,
        lease_owner: str,
        now: datetime,
        *,
        crash_after_business_marker: bool = False,
    ) -> dict[str, Any]:
        """Run or replay the fake mutation."""
        request_hash = f"sha256:fake:{project_id}:{changed_by}"
        loaded = self._ledger.create_or_load(
            command="agileforge fake mutate",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            project_id=project_id,
            correlation_id=correlation_id,
            changed_by=changed_by,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        )
        if loaded.response is not None:
            return loaded.response
        if loaded.error_code is not None:
            return {
                "ok": False,
                "data": None,
                "warnings": [],
                "errors": [
                    {
                        "code": loaded.error_code,
                        "message": "Mutation cannot run.",
                        "details": {
                            "mutation_event_id": loaded.ledger.mutation_event_id
                        },
                        "remediation": [
                            "agileforge mutation show --mutation-event-id "
                            f"{loaded.ledger.mutation_event_id}"
                        ],
                        "exit_code": 1,
                        "retryable": True,
                    }
                ],
            }

        event_id = loaded.ledger.mutation_event_id
        if event_id is None:
            raise RuntimeError("Mutation ledger row has no primary key.")

        if not self._ledger.require_active_owner(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        ):
            return self._error(MUTATION_RESUME_CONFLICT, event_id)
        self._side_effects.write_business_marker(project_id)
        self._ledger.mark_step_complete(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            step="business_marker",
            next_step="session_marker",
            now=now,
        )
        if crash_after_business_marker:
            raise FakeMutationCrash("Simulated crash after business marker.")

        if not self._ledger.require_active_owner(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        ):
            return self._error(MUTATION_RESUME_CONFLICT, event_id)
        self._side_effects.write_session_marker(project_id)
        self._ledger.mark_step_complete(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            step="session_marker",
            next_step="done",
            now=now,
        )
        response = {
            "ok": True,
            "data": {
                "project_id": project_id,
                "mutation_event_id": event_id,
                "next_actions": [],
            },
            "warnings": [],
            "errors": [],
        }
        self._ledger.finalize_success(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            after={"business_marker": True, "session_marker": True},
            response=response,
            now=now,
        )
        return response

    def resume(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Resume the original fake mutation without accepting new domain args."""
        acquired = self._ledger.acquire_resume_lease(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        )
        if acquired.error_code is not None:
            return self._error(acquired.error_code, mutation_event_id)
        project_id = acquired.ledger.project_id
        if project_id is None:
            return self._error(MUTATION_RECOVERY_REQUIRED, mutation_event_id)
        if not self._ledger.require_active_owner(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        ):
            return self._error(MUTATION_RESUME_CONFLICT, mutation_event_id)
        self._side_effects.write_session_marker(project_id)
        self._ledger.mark_step_complete(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            step="session_marker",
            next_step="done",
            now=now,
        )
        response = {
            "ok": True,
            "data": {
                "project_id": project_id,
                "mutation_event_id": mutation_event_id,
                "resumed_steps": ["session_marker"],
            },
            "warnings": [],
            "errors": [],
        }
        self._ledger.finalize_success(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            after={"business_marker": True, "session_marker": True},
            response=response,
            now=now,
        )
        return response

    def _error(self, code: str, mutation_event_id: int) -> dict[str, Any]:
        return {
            "ok": False,
            "data": None,
            "warnings": [],
            "errors": [
                {
                    "code": code,
                    "message": "Mutation cannot run.",
                    "details": {"mutation_event_id": mutation_event_id},
                    "remediation": [
                        f"agileforge mutation show --mutation-event-id {mutation_event_id}"
                    ],
                    "exit_code": 1,
                    "retryable": True,
                }
            ],
        }
```

- [ ] **Step 4: Run fake mutation tests and commit**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_fake_mutation.py tests/test_agent_workbench_mutation_ledger.py -q
```

Expected: PASS.

Commit:

```bash
git add services/agent_workbench/fake_mutation.py tests/test_agent_workbench_fake_mutation.py
git commit -m "test: prove CLI mutation contract harness"
```

---

### Task 6: CLI Operational Commands

**Files:**
- Modify: `cli/main.py`
- Modify: `services/agent_workbench/application.py`
- Test: `tests/test_agent_workbench_cli.py`

- [ ] **Step 1: Write failing CLI routing tests**

Extend `_FakeApplication` in `tests/test_agent_workbench_cli.py`:

```python
    def doctor(self) -> JsonObject:
        self.calls.append(("doctor", {}))
        return {"ok": True, "data": {"checks": []}, "warnings": [], "errors": []}

    def schema_check(self) -> JsonObject:
        self.calls.append(("schema_check", {}))
        return {"ok": True, "data": {"stores": []}, "warnings": [], "errors": []}

    def capabilities(self) -> JsonObject:
        self.calls.append(("capabilities", {}))
        return {"ok": True, "data": {"commands": []}, "warnings": [], "errors": []}

    def command_schema(self, *, command_name: str) -> JsonObject:
        self.calls.append(("command_schema", {"command_name": command_name}))
        return {"ok": True, "data": {"name": command_name}, "warnings": [], "errors": []}

    def mutation_show(self, *, mutation_event_id: int) -> JsonObject:
        self.calls.append(("mutation_show", {"mutation_event_id": mutation_event_id}))
        return {"ok": True, "data": {"mutation_event_id": mutation_event_id}, "warnings": [], "errors": []}

    def mutation_list(self, *, project_id: int | None = None, status: str | None = None) -> JsonObject:
        self.calls.append(("mutation_list", {"project_id": project_id, "status": status}))
        return {"ok": True, "data": {"items": []}, "warnings": [], "errors": []}

    def mutation_resume(self, *, mutation_event_id: int, correlation_id: str | None = None) -> JsonObject:
        self.calls.append(("mutation_resume", {"mutation_event_id": mutation_event_id, "correlation_id": correlation_id}))
        return {"ok": True, "data": {"mutation_event_id": mutation_event_id}, "warnings": [], "errors": []}
```

Add tests:

```python
@pytest.mark.parametrize(
    ("argv", "expected_call"),
    [
        (["doctor"], ("doctor", {})),
        (["schema", "check"], ("schema_check", {})),
        (["capabilities"], ("capabilities", {})),
        (
            ["command", "schema", "agileforge status"],
            ("command_schema", {"command_name": "agileforge status"}),
        ),
        (
            ["mutation", "show", "--mutation-event-id", "101"],
            ("mutation_show", {"mutation_event_id": 101}),
        ),
        (
            ["mutation", "list", "--project-id", "7", "--status", "recovery_required"],
            ("mutation_list", {"project_id": 7, "status": "recovery_required"}),
        ),
        (
            ["mutation", "resume", "--mutation-event-id", "101", "--correlation-id", "corr-1"],
            ("mutation_resume", {"mutation_event_id": 101, "correlation_id": "corr-1"}),
        ),
    ],
)
def test_cli_routes_phase_2a_operational_commands(
    argv: list[str],
    expected_call: tuple[str, dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = _FakeApplication()

    rc = main(argv, application=app)

    assert rc == 0
    _stdout_payload(capsys)
    assert app.calls == [expected_call]
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_cli.py -q
```

Expected: FAIL because the parser has no Phase 2A operational commands.

- [ ] **Step 3: Add application protocol and parser routes**

Modify `_Application` in `cli/main.py` to add:

```python
    def doctor(self) -> JsonObject: ...
    def schema_check(self) -> JsonObject: ...
    def capabilities(self) -> JsonObject: ...
    def command_schema(self, *, command_name: str) -> JsonObject: ...
    def mutation_show(self, *, mutation_event_id: int) -> JsonObject: ...
    def mutation_list(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
    ) -> JsonObject: ...
    def mutation_resume(
        self,
        *,
        mutation_event_id: int,
        correlation_id: str | None = None,
    ) -> JsonObject: ...
```

Add parser definitions in `build_parser()` after `status`:

```python
    doctor = subparsers.add_parser("doctor", help="Run CLI diagnostics.")
    doctor.set_defaults(command_handler=_doctor)

    capabilities = subparsers.add_parser(
        "capabilities",
        help="Show installed command capabilities.",
    )
    capabilities.set_defaults(command_handler=_capabilities)

    schema = subparsers.add_parser("schema", help="Inspect CLI schemas.")
    schema_sub = schema.add_subparsers(
        dest="action",
        required=True,
        parser_class=_WorkbenchArgumentParser,
    )
    schema_check = schema_sub.add_parser("check", help="Check storage schema.")
    schema_check.set_defaults(command_handler=_schema_check)

    command = subparsers.add_parser("command", help="Inspect command contracts.")
    command_sub = command.add_subparsers(
        dest="action",
        required=True,
        parser_class=_WorkbenchArgumentParser,
    )
    command_schema = command_sub.add_parser("schema", help="Show command schema.")
    command_schema.add_argument("command_name")
    command_schema.set_defaults(command_handler=_command_schema)

    mutation = subparsers.add_parser("mutation", help="Inspect mutation ledger.")
    mutation_sub = mutation.add_subparsers(
        dest="action",
        required=True,
        parser_class=_WorkbenchArgumentParser,
    )
    mutation_show = mutation_sub.add_parser("show", help="Show one mutation event.")
    mutation_show.add_argument("--mutation-event-id", type=int, required=True)
    mutation_show.set_defaults(command_handler=_mutation_show)
    mutation_list = mutation_sub.add_parser("list", help="List mutation events.")
    mutation_list.add_argument("--project-id", type=int)
    mutation_list.add_argument("--status")
    mutation_list.set_defaults(command_handler=_mutation_list)
    mutation_resume = mutation_sub.add_parser(
        "resume",
        help="Resume a recovery-required mutation event.",
    )
    mutation_resume.add_argument("--mutation-event-id", type=int, required=True)
    mutation_resume.add_argument("--correlation-id")
    mutation_resume.set_defaults(command_handler=_mutation_resume)
```

Add route functions:

```python
def _doctor(_args: argparse.Namespace, application: _Application) -> CommandResult:
    return "agileforge doctor", application.doctor()


def _schema_check(
    _args: argparse.Namespace,
    application: _Application,
) -> CommandResult:
    return "agileforge schema check", application.schema_check()


def _capabilities(
    _args: argparse.Namespace,
    application: _Application,
) -> CommandResult:
    return "agileforge capabilities", application.capabilities()


def _command_schema(
    args: argparse.Namespace,
    application: _Application,
) -> CommandResult:
    return "agileforge command schema", application.command_schema(
        command_name=args.command_name,
    )


def _mutation_show(
    args: argparse.Namespace,
    application: _Application,
) -> CommandResult:
    return "agileforge mutation show", application.mutation_show(
        mutation_event_id=args.mutation_event_id,
    )


def _mutation_list(
    args: argparse.Namespace,
    application: _Application,
) -> CommandResult:
    return "agileforge mutation list", application.mutation_list(
        project_id=args.project_id,
        status=args.status,
    )


def _mutation_resume(
    args: argparse.Namespace,
    application: _Application,
) -> CommandResult:
    return "agileforge mutation resume", application.mutation_resume(
        mutation_event_id=args.mutation_event_id,
        correlation_id=args.correlation_id,
    )
```

- [ ] **Step 4: Add facade methods for mutation ledger inspection**

Modify `services/agent_workbench/application.py` to import `MutationLedgerRepository` and `get_engine`, then add:

```python
    def mutation_show(self, *, mutation_event_id: int) -> dict[str, Any]:
        """Return one mutation ledger event."""
        repo = MutationLedgerRepository(engine=get_engine())
        return repo.show_event(mutation_event_id=mutation_event_id)

    def mutation_list(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Return mutation ledger events."""
        repo = MutationLedgerRepository(engine=get_engine())
        return repo.list_events(project_id=project_id, status=status)

    def mutation_resume(
        self,
        *,
        mutation_event_id: int,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Acquire a guarded recovery lease for a mutation event."""
        repo = MutationLedgerRepository(engine=get_engine())
        return repo.resume_event(
            mutation_event_id=mutation_event_id,
            correlation_id=correlation_id,
        )
```

If `MutationLedgerRepository.show_event`, `list_events`, or `resume_event` do not exist yet, add them in `mutation_ledger.py` with the same envelope shape used by other facade methods:

```python
def show_event(self, *, mutation_event_id: int) -> dict[str, Any]:
    with Session(self._engine) as session:
        row = session.get(CliMutationLedger, mutation_event_id)
        if row is None:
            return {
                "ok": False,
                "data": None,
                "warnings": [],
                "errors": [
                    {
                        "code": "MUTATION_NOT_FOUND",
                        "message": "Mutation event was not found.",
                        "details": {"mutation_event_id": mutation_event_id},
                        "remediation": ["agileforge mutation list"],
                        "exit_code": 4,
                        "retryable": False,
                    }
                ],
            }
        return {"ok": True, "data": self._row_payload(row), "warnings": [], "errors": []}
```

- [ ] **Step 5: Run CLI tests and commit**

Run:

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_cli.py tests/test_agent_workbench_application.py -q
```

Expected: PASS.

Commit:

```bash
git add cli/main.py services/agent_workbench/application.py services/agent_workbench/mutation_ledger.py tests/test_agent_workbench_cli.py
git commit -m "feat: add CLI contract operations"
```

---

### Task 7: Full Contract Regression Pass

**Files:**
- Modify: `tests/test_agent_workbench_phase1_integration.py`
- Modify: `tests/test_agent_workbench_schema_readiness.py`
- Modify: read-command tests that assert exact `meta`

- [ ] **Step 1: Update envelope fixture assertions**

Where tests assert exact `meta`, update them to assert the enriched fields:

```python
meta = _mapping(payload["meta"])
assert meta["schema_version"] == "agileforge.cli.v1"
assert meta["command"] == expected_command
assert meta["command_version"] == "1"
assert meta["agileforge_version"]
assert meta["storage_schema_version"] == "1"
assert meta["correlation_id"]
assert meta["generated_at"]
```

- [ ] **Step 2: Add import-boundary regression for Phase 2A commands**

Extend `tests/test_agent_tool_runtime_import_boundary.py` or create `tests/test_agent_workbench_contract_import_boundary.py`:

```python
"""Import-boundary tests for CLI contract hardening modules."""

import sys


def test_contract_modules_do_not_import_fastapi_api() -> None:
    import services.agent_workbench.command_schema  # noqa: F401
    import services.agent_workbench.diagnostics  # noqa: F401
    import services.agent_workbench.mutation_ledger  # noqa: F401

    assert "api" not in sys.modules
```

- [ ] **Step 3: Run focused contract suite**

Run:

```bash
uv run --frozen python -m pytest \
  tests/test_agent_workbench_error_codes.py \
  tests/test_agent_workbench_version.py \
  tests/test_agent_workbench_envelope.py \
  tests/test_agent_workbench_command_schema.py \
  tests/test_agent_workbench_diagnostics.py \
  tests/test_agent_workbench_mutation_ledger.py \
  tests/test_agent_workbench_fake_mutation.py \
  tests/test_agent_workbench_cli.py \
  tests/test_agent_workbench_phase1_integration.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Run full test suite**

Run:

```bash
uv run --frozen python -m pytest tests/ -q
```

Expected: PASS.

- [ ] **Step 5: Verify central shim behavior still works outside the repo**

Run:

```bash
tmp_dir="$(mktemp -d)"
cd "$tmp_dir"
agileforge capabilities
agileforge doctor
```

Expected: both commands emit JSON envelopes. `doctor` may report blocked project storage if runtime configuration points to a missing database, but it must not fail due to cwd-relative AgileForge resource resolution.

- [ ] **Step 6: Commit final regression updates**

```bash
git add tests/test_agent_workbench_phase1_integration.py tests/test_agent_workbench_schema_readiness.py tests/test_agent_workbench_contract_import_boundary.py
git commit -m "test: cover CLI contract hardening regressions"
```

---

## Self-Review Checklist

- Spec coverage: This plan implements Phase 2A only: envelope metadata, error registry, command registry enrichment, diagnostics, schema check, capabilities, command schema, mutation ledger, dry-run semantics, recovery fencing, mutation operations, fake mutation harness, and regression coverage.
- Out of scope: `project create`, authority compile/accept CLI, vision/backlog/roadmap mutations, story/sprint/task mutations, project delete, workflow reset, and artifact clear.
- Critical sequencing: Task 1 builds the ledger state machine first. Task 5 proves the contract through a two-boundary fake mutation before real domain mutations exist.
- Safety: `mutation show/list` are read-only. `mutation resume` is mutating and must be marked as mutating in command metadata.
- Recovery: `mutation resume` mutates only the existing ledger row, uses a CAS transition from `recovery_required` to `pending`, and resumes the original mutation without accepting replacement domain arguments.
- Stale pending: The production default is `DEFAULT_STALE_PENDING_TIMEOUT_SECONDS = 300`, with shorter test lease values used only for fast stale-pending coverage.
- Guardrails: `meta.source_fingerprint` is not reused as `data.guard_tokens`; guard-token producer work is limited to schema declarations in Phase 2A.
