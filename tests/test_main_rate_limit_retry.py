import asyncio

import pytest

import main


class DummyRunner:
    pass


@pytest.mark.asyncio
async def test_rate_limit_retries_then_success(monkeypatch):
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1
        if calls["count"] < 3:
            raise Exception("RateLimitError: retry")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "RATE_LIMIT_MAX_RETRIES", 3)
    monkeypatch.setattr(main, "RATE_LIMIT_MAX_BACKOFF_SECONDS", 0)

    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_rate_limit_retries_exhausted(monkeypatch):
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1
        raise Exception("RateLimitError: retry")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "RATE_LIMIT_MAX_RETRIES", 2)
    monkeypatch.setattr(main, "RATE_LIMIT_MAX_BACKOFF_SECONDS", 0)

    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 3