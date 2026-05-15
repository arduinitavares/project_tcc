"""Tests for CLI mutation ledger state transitions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine
from sqlalchemy.sql.dml import Update
from sqlmodel import Session, SQLModel, select

import services.agent_workbench.mutation_ledger as mutation_ledger_mod
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
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


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


def test_offset_aware_create_timestamps_are_stored_as_utc_instants(
    engine: Engine,
) -> None:
    repo = _repo(engine)
    offset_now = datetime(2026, 5, 15, 15, 0, tzinfo=timezone(timedelta(hours=3)))

    result = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=offset_now,
        lease_seconds=30,
    )

    assert result.ledger.lease_acquired_at == datetime(2026, 5, 15, 12, 0)
    assert result.ledger.last_heartbeat_at == datetime(2026, 5, 15, 12, 0)
    assert result.ledger.lease_expires_at == datetime(2026, 5, 15, 12, 0, 30)


def test_create_or_load_handles_unique_constraint_insert_race(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    original_commit = mutation_ledger_mod.Session.commit
    raced = False
    inserting_competing_row = False

    def commit_with_insert_race(session: Session) -> None:
        nonlocal raced, inserting_competing_row
        if (
            not raced
            and not inserting_competing_row
            and any(isinstance(item, CliMutationLedger) for item in session.new)
        ):
            raced = True
            inserting_competing_row = True
            with Session(engine) as competing_session:
                competing_session.add(
                    CliMutationLedger(
                        command="agileforge fake mutate",
                        idempotency_key="fake-key-001",
                        request_hash="sha256:req",
                        project_id=7,
                        correlation_id="corr-race",
                        changed_by="cli-agent",
                        status=MutationStatus.PENDING.value,
                        lease_owner="worker-race",
                        lease_acquired_at=_db_time(now),
                        last_heartbeat_at=_db_time(now),
                        lease_expires_at=_db_time(now + timedelta(seconds=30)),
                        created_at=_db_time(now),
                        updated_at=_db_time(now),
                    )
                )
                original_commit(competing_session)
            inserting_competing_row = False
            raise IntegrityError("insert race", params=None, orig=Exception("unique"))
        original_commit(session)

    monkeypatch.setattr(mutation_ledger_mod.Session, "commit", commit_with_insert_race)

    result = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=now + timedelta(seconds=1),
        lease_seconds=30,
    )

    assert result.error_code == MUTATION_IN_PROGRESS
    assert result.ledger.lease_owner == "worker-race"
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


def test_stale_pending_error_timestamp_uses_utc_instant_for_offset_now(
    engine: Engine,
) -> None:
    repo = _repo(engine)
    created_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    offset_now = datetime(2026, 5, 15, 15, 0, 45, tzinfo=timezone(timedelta(hours=3)))
    row = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=created_at,
        lease_seconds=30,
    ).ledger
    assert row.mutation_event_id is not None

    result = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-2",
        changed_by="cli-agent",
        lease_owner="worker-2",
        now=offset_now,
        lease_seconds=30,
    )

    assert result.error_code == MUTATION_RECOVERY_REQUIRED
    with Session(engine) as session:
        stored = session.exec(select(CliMutationLedger)).one()
    assert stored.last_error_json is not None
    last_error = json.loads(stored.last_error_json)
    assert last_error["recorded_at"] == "2026-05-15T12:00:45+00:00"


def test_stale_recovery_loses_race_when_same_owner_refreshes_lease(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
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
    recovery_attempt_at = now + timedelta(seconds=45)
    refreshed_expires_at = recovery_attempt_at + timedelta(seconds=60)
    original_exec = mutation_ledger_mod.Session.exec
    race_injected = False

    def exec_with_lease_refresh_race(
        session: Session,
        statement: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal race_injected
        if isinstance(statement, Update) and not race_injected:
            race_injected = True
            original_exec(
                session,
                update(CliMutationLedger)
                .where(CliMutationLedger.mutation_event_id == row.mutation_event_id)
                .values(
                    last_heartbeat_at=_db_time(recovery_attempt_at),
                    lease_expires_at=_db_time(refreshed_expires_at),
                    updated_at=_db_time(recovery_attempt_at),
                ),
            )
        return original_exec(session, statement, *args, **kwargs)

    monkeypatch.setattr(mutation_ledger_mod.Session, "exec", exec_with_lease_refresh_race)

    result = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=7,
        correlation_id="corr-2",
        changed_by="cli-agent",
        lease_owner="worker-2",
        now=recovery_attempt_at,
        lease_seconds=30,
    )

    assert result.error_code == MUTATION_IN_PROGRESS
    with Session(engine) as session:
        stored = session.exec(select(CliMutationLedger)).one()
    assert stored.status == MutationStatus.PENDING.value
    assert stored.lease_owner == "worker-1"
    assert stored.lease_expires_at == _db_time(refreshed_expires_at)
    assert stored.last_error_json is None


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
    assert not hasattr(repo, "force_recovery_required")
    repo._force_recovery_required_for_test(
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


def test_expired_owner_cannot_heartbeat(engine: Engine) -> None:
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

    refreshed = repo.require_active_owner(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        now=now + timedelta(seconds=30),
        lease_seconds=30,
    )

    assert refreshed is False
    with Session(engine) as session:
        stored = session.get(CliMutationLedger, row.mutation_event_id)
    assert stored is not None
    assert stored.last_heartbeat_at == _db_time(now)
    assert stored.lease_expires_at == _db_time(now + timedelta(seconds=30))


def test_expired_owner_cannot_mark_step_complete(engine: Engine) -> None:
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

    marked = repo.mark_step_complete(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        step="business_marker",
        next_step="session_marker",
        now=now + timedelta(seconds=30),
    )

    assert marked is False
    with Session(engine) as session:
        stored = session.get(CliMutationLedger, row.mutation_event_id)
    assert stored is not None
    assert stored.completed_steps_json == "[]"
    assert stored.current_step == "start"


def test_expired_owner_cannot_finalize_success(engine: Engine) -> None:
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

    finalized = repo.finalize_success(
        mutation_event_id=row.mutation_event_id,
        lease_owner="worker-1",
        after={"step": "done"},
        response={"ok": True},
        now=now + timedelta(seconds=30),
    )

    assert finalized is False
    with Session(engine) as session:
        stored = session.get(CliMutationLedger, row.mutation_event_id)
    assert stored is not None
    assert stored.status == MutationStatus.PENDING.value
    assert stored.after_json is None
    assert stored.response_json is None
    assert stored.lease_owner == "worker-1"


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
