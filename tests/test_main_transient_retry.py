import asyncio

import pytest

import main


class DummyRunner:
    pass


@pytest.mark.asyncio
async def test_transient_retries_then_success(monkeypatch):
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1
        if calls["count"] < 2:
            raise Exception("OpenrouterException - Unable to get json response")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "TRANSIENT_MAX_RETRIES", 2)
    monkeypatch.setattr(main, "TRANSIENT_MAX_BACKOFF_SECONDS", 0)

    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_transient_retries_exhausted(monkeypatch):
    calls = {"count": 0}

    async def fake_run_agent_turn(_runner, _user_input, is_system_trigger=False):
        calls["count"] += 1
        raise Exception("OpenrouterException - Unable to get json response")

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(main, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "TRANSIENT_MAX_RETRIES", 1)
    monkeypatch.setattr(main, "TRANSIENT_MAX_BACKOFF_SECONDS", 0)

    await main.run_user_turn_with_retries(DummyRunner(), "hello")

    assert calls["count"] == 2