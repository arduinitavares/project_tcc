"""Tests for transient error handling in run_user_turn_with_retries.

Retry logic is now handled internally by SelfHealingAgent.
run_user_turn_with_retries catches and logs errors without re-raising.
"""

import pytest

import main


class DummyRunner:
    pass


@pytest.mark.asyncio
async def test_transient_error_caught_not_propagated(monkeypatch):
    """Transient errors are caught and logged, not re-raised."""
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1
        raise Exception("OpenrouterException - Unable to get json response")

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)

    # Should NOT raise
    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_successful_turn_completes(monkeypatch):
    """Successful turn runs once without error."""
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)

    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 1