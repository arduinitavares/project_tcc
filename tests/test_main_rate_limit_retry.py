"""Tests for run_user_turn_with_retries.

Retry logic (rate-limit, transient) is now handled internally by
SelfHealingAgent.  run_user_turn_with_retries simply delegates to
run_agent_turn and catches any exception that bubbles up.
"""

import pytest

import main


class DummyRunner:
    pass


@pytest.mark.asyncio
async def test_successful_turn_calls_run_agent_turn(monkeypatch):
    """A successful turn completes without error."""
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)

    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_failed_turn_does_not_propagate(monkeypatch):
    """Errors are caught and logged, not re-raised."""
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1
        raise Exception("RateLimitError: retry")

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)

    # Should NOT raise
    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 1