"""Tests for CLI mutation ledger state transitions."""

from __future__ import annotations

import json
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


def _db_time(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def test_create_pending_row_records_request_hash_and_lease(engine: Engine) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    result = repo.create_or_load(
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

    assert result.replayed is False
    assert result.error_code is None
    assert result.ledger.command == "agileforge fake mutate"
    assert result.ledger.idempotency_key == "fake-key-001"
    assert result.ledger.request_hash == "sha256:req"
    assert result.ledger.project_id == 7
    assert result.ledger.correlation_id == "corr-1"
    assert result.ledger.changed_by == "cli-agent"
    assert result.ledger.status == MutationStatus.PENDING.value
    assert result.ledger.lease_owner == "worker-1"
    assert result.ledger.lease_acquired_at == _db_time(now)
    assert result.ledger.last_heartbeat_at == _db_time(now)
    assert result.ledger.lease_expires_at == _db_time(now + timedelta(seconds=30))
    assert result.ledger.current_step == "start"

    with Session(engine) as session:
        rows = session.exec(select(CliMutationLedger)).all()
    assert len(rows) == 1


def test_same_key_same_request_replays_success_without_new_row(
    engine: Engine,
) -> None:
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

    assert row.mutation_event_id is not None
    assert repo.finalize_success(
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
    assert replay.ledger.mutation_event_id == row.mutation_event_id
    assert replay.ledger.status == MutationStatus.SUCCEEDED.value
    assert replay.response == {"ok": True, "data": {"result": "done"}}
    with Session(engine) as session:
        rows = session.exec(select(CliMutationLedger)).all()
    assert len(rows) == 1


def test_same_key_different_request_returns_reuse_error(engine: Engine) -> None:
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
    with Session(engine) as session:
        rows = session.exec(select(CliMutationLedger)).all()
    assert len(rows) == 1


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


def test_stale_pending_becomes_recovery_required_with_structured_error(
    engine: Engine,
) -> None:
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
    assert row.mutation_event_id is not None
    assert repo.mark_step_complete(
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
    assert stored.lease_owner is None
    assert stored.lease_expires_at is None
    assert stored.recovery_action == RecoveryAction.RECONCILE_THEN_RESUME.value
    assert stored.recovery_safe_to_auto_resume is False
    assert stored.last_error_json is not None
    last_error = json.loads(stored.last_error_json)
    assert last_error == {
        "code": "STALE_PENDING",
        "message": "Pending mutation lease expired.",
        "details": {"current_step": "session_marker"},
        "retryable": True,
        "recorded_at": (now + timedelta(seconds=45)).isoformat(),
    }


def test_resume_requires_compare_and_set_from_recovery_required(
    engine: Engine,
) -> None:
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
    assert row.mutation_event_id is not None
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
    assert acquired.ledger.lease_acquired_at == _db_time(
        now + timedelta(seconds=2)
    )
    assert acquired.ledger.lease_expires_at == _db_time(now + timedelta(seconds=32))
    assert conflicted.error_code == MUTATION_RESUME_CONFLICT


def test_transition_status_enforces_expected_status_and_owner(
    engine: Engine,
) -> None:
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
    assert row.mutation_event_id is not None

    wrong_owner = repo.transition_status(
        mutation_event_id=row.mutation_event_id,
        expected_status=MutationStatus.PENDING,
        expected_lease_owner="worker-2",
        new_status=MutationStatus.RECOVERY_REQUIRED,
        new_lease_owner=None,
        now=now + timedelta(seconds=1),
    )
    wrong_status = repo.transition_status(
        mutation_event_id=row.mutation_event_id,
        expected_status=MutationStatus.RECOVERY_REQUIRED,
        expected_lease_owner="worker-1",
        new_status=MutationStatus.SUCCEEDED,
        new_lease_owner=None,
        now=now + timedelta(seconds=1),
    )
    transitioned = repo.transition_status(
        mutation_event_id=row.mutation_event_id,
        expected_status=MutationStatus.PENDING,
        expected_lease_owner="worker-1",
        new_status=MutationStatus.RECOVERY_REQUIRED,
        new_lease_owner=None,
        now=now + timedelta(seconds=2),
    )

    assert wrong_owner.error_code == MUTATION_RESUME_CONFLICT
    assert wrong_status.error_code == MUTATION_RESUME_CONFLICT
    assert transitioned.error_code is None
    assert transitioned.ledger.status == MutationStatus.RECOVERY_REQUIRED.value
    assert transitioned.ledger.lease_owner is None


def test_require_active_owner_refreshes_only_active_owner(engine: Engine) -> None:
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
    assert row.mutation_event_id is not None

    wrong_owner = repo.require_active_owner(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-2",
        now=now + timedelta(seconds=5),
        lease_seconds=30,
    )
    active_owner = repo.require_active_owner(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        now=now + timedelta(seconds=10),
        lease_seconds=30,
    )

    assert wrong_owner is False
    assert active_owner is True
    with Session(engine) as session:
        stored = session.get(CliMutationLedger, row.mutation_event_id)
    assert stored is not None
    assert stored.last_heartbeat_at == _db_time(now + timedelta(seconds=10))
    assert stored.lease_expires_at == _db_time(now + timedelta(seconds=40))


def test_finalize_success_requires_pending_active_owner_and_stores_result(
    engine: Engine,
) -> None:
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
    assert row.mutation_event_id is not None

    assert not repo.finalize_success(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-2",
        after={"step": "wrong"},
        response={"ok": False},
        now=now + timedelta(seconds=1),
    )
    assert repo.finalize_success(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        after={"step": "done"},
        response={"ok": True, "data": {"result": "done"}},
        now=now + timedelta(seconds=2),
    )
    assert not repo.finalize_success(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        after={"step": "again"},
        response={"ok": True},
        now=now + timedelta(seconds=3),
    )

    with Session(engine) as session:
        stored = session.get(CliMutationLedger, row.mutation_event_id)
    assert stored is not None
    assert stored.status == MutationStatus.SUCCEEDED.value
    assert json.loads(stored.after_json or "{}") == {"step": "done"}
    assert json.loads(stored.response_json or "{}") == {
        "ok": True,
        "data": {"result": "done"},
    }
    assert stored.lease_owner is None
    assert stored.lease_expires_at is None
    assert stored.recovery_action == RecoveryAction.NONE.value
