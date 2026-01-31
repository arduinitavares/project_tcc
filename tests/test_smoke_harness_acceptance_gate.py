"""Tests for smoke harness acceptance gate behavior."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from scripts.smoke_spec_to_story_pipeline import _build_trace_base, _handle_unaccepted_spec


def test_acceptance_gate_blocks_unaccepted_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    trace: Dict[str, Any] = _build_trace_base()
    called = {"count": 0}

    def should_not_run() -> None:
        called["count"] += 1
        raise AssertionError("Story pipeline should not be called when not accepted")

    blocked = _handle_unaccepted_spec(
        trace=trace,
        spec_version_id=99,
        spec_accepted=False,
        run_story_pipeline=should_not_run,
    )

    assert blocked is True
    assert trace["ACCEPTANCE_GATE_BLOCKED"] is True
    assert trace["SPEC_ACCEPTED"] is False
    assert trace["PINNED_SPEC_VERSION_ID"] == 99
    assert trace["DRAFT_AGENT_OUTPUT"] is None
    assert trace["REFINER_OUTPUT"] is None
    assert trace["VALIDATION_RESULT"] is None
    assert trace["EVIDENCE_RECORD"] is None
    assert called["count"] == 0
