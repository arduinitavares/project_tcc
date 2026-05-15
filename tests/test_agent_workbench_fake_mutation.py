"""Tests for the Phase 2A fake mutation harness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from services.agent_workbench.fake_mutation import (
    FAKE_MUTATION_FINALIZE_FAILED,
    FakeMutationCrash,
    FakeMutationRunner,
    FakeSideEffectSink,
)
from services.agent_workbench.mutation_ledger import (
    IDEMPOTENCY_KEY_REUSED,
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


def test_fake_mutation_crash_after_first_step_requires_recovery(
    engine: Engine,
) -> None:
    runner, sink = _runner(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    with pytest.raises(FakeMutationCrash):
        runner.run(
            7,
            "fake-key-001",
            "corr-1",
            "cli-agent",
            "worker-1",
            now,
            crash_after_business_marker=True,
        )

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

    with pytest.raises(FakeMutationCrash):
        runner.run(
            7,
            "fake-key-001",
            "corr-1",
            "cli-agent",
            "worker-1",
            now,
            crash_after_business_marker=True,
        )

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


def test_fake_mutation_reused_idempotency_key_with_different_request_errors(
    engine: Engine,
) -> None:
    runner, sink = _runner(engine)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    runner.run(7, "fake-key-001", "corr-1", "cli-agent", "worker-1", now)
    result = runner.run(
        8,
        "fake-key-001",
        "corr-2",
        "cli-agent",
        "worker-2",
        now + timedelta(seconds=1),
    )

    assert result["ok"] is False
    assert result["errors"][0]["code"] == IDEMPOTENCY_KEY_REUSED
    assert sink.business_markers == [7]
    assert sink.session_markers == [7]


def test_fake_mutation_failed_finalization_returns_error(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    SQLModel.metadata.create_all(engine)
    sink = FakeSideEffectSink()
    repo = MutationLedgerRepository(engine=engine)
    runner = FakeMutationRunner(ledger=repo, side_effects=sink)
    now = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(repo, "finalize_success", lambda **_: False)

    result = runner.run(7, "fake-key-001", "corr-1", "cli-agent", "worker-1", now)

    assert result["ok"] is False
    assert result["errors"][0]["code"] == FAKE_MUTATION_FINALIZE_FAILED
    assert sink.business_markers == [7]
    assert sink.session_markers == [7]
