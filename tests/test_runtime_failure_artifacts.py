from __future__ import annotations

from typing import Any, Callable, Dict

import pytest

from services import backlog_runtime, roadmap_runtime, story_runtime, vision_runtime
from utils.failure_artifacts import AgentInvocationError
import utils.failure_artifacts as failure_artifacts


RuntimeCase = Dict[str, Any]


def _story_state() -> Dict[str, Any]:
    return {
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
    }


def _vision_state() -> Dict[str, Any]:
    return {
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
    }


def _backlog_state() -> Dict[str, Any]:
    return {
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "product_vision_assessment": {
            "product_vision_statement": "Vision statement",
        },
    }


def _roadmap_state() -> Dict[str, Any]:
    return {
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
        "product_vision_assessment": {
            "product_vision_statement": "Vision statement",
        },
        "backlog_items": [],
    }


RUNTIME_CASES: list[RuntimeCase] = [
    {
        "phase": "story",
        "module": story_runtime,
        "invoke_name": "_invoke_story_agent",
        "run": story_runtime.run_story_agent_from_state,
        "state_factory": _story_state,
        "kwargs_factory": lambda: {
            "project_id": 1,
            "parent_requirement": "Requirement A",
            "user_input": None,
        },
    },
    {
        "phase": "vision",
        "module": vision_runtime,
        "invoke_name": "_invoke_vision_agent",
        "run": vision_runtime.run_vision_agent_from_state,
        "state_factory": _vision_state,
        "kwargs_factory": lambda: {
            "project_id": 1,
            "user_input": "",
        },
    },
    {
        "phase": "backlog",
        "module": backlog_runtime,
        "invoke_name": "_invoke_backlog_agent",
        "run": backlog_runtime.run_backlog_agent_from_state,
        "state_factory": _backlog_state,
        "kwargs_factory": lambda: {
            "project_id": 1,
            "user_input": "",
        },
    },
    {
        "phase": "roadmap",
        "module": roadmap_runtime,
        "invoke_name": "_invoke_roadmap_agent",
        "run": roadmap_runtime.run_roadmap_agent_from_state,
        "state_factory": _roadmap_state,
        "kwargs_factory": lambda: {
            "project_id": 1,
            "user_input": "",
        },
    },
]


def _patch_failure_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(failure_artifacts, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(failure_artifacts, "FAILURES_DIR", tmp_path / "logs" / "failures")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", RUNTIME_CASES, ids=lambda case: case["phase"])
async def test_runtime_invalid_json_writes_full_failure_artifact(monkeypatch, tmp_path, case: RuntimeCase):
    _patch_failure_dir(monkeypatch, tmp_path)

    async def fake_invoke(_payload):
        return '{"broken": '

    monkeypatch.setattr(case["module"], case["invoke_name"], fake_invoke)

    result = await case["run"](case["state_factory"](), **case["kwargs_factory"]())
    assert result["success"] is False
    assert result["failure_stage"] == "invalid_json"
    assert result["failure_artifact_id"] is not None
    assert result["has_full_artifact"] is True

    artifact = failure_artifacts.read_failure_artifact(result["failure_artifact_id"])
    assert artifact is not None
    assert artifact["phase"] == case["phase"]
    assert artifact["raw_output"] == '{"broken": '


@pytest.mark.asyncio
@pytest.mark.parametrize("case", RUNTIME_CASES, ids=lambda case: case["phase"])
async def test_runtime_output_validation_writes_full_failure_artifact(monkeypatch, tmp_path, case: RuntimeCase):
    _patch_failure_dir(monkeypatch, tmp_path)

    async def fake_invoke(_payload):
        return "{}"

    monkeypatch.setattr(case["module"], case["invoke_name"], fake_invoke)

    result = await case["run"](case["state_factory"](), **case["kwargs_factory"]())
    assert result["success"] is False
    assert result["failure_stage"] == "output_validation"
    assert result["failure_artifact_id"] is not None

    artifact = failure_artifacts.read_failure_artifact(result["failure_artifact_id"])
    assert artifact is not None
    assert artifact["phase"] == case["phase"]
    assert artifact["raw_output"] == "{}"
    assert artifact["validation_errors"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", RUNTIME_CASES, ids=lambda case: case["phase"])
async def test_runtime_invocation_exception_persists_partial_output(monkeypatch, tmp_path, case: RuntimeCase):
    _patch_failure_dir(monkeypatch, tmp_path)

    async def fake_invoke(_payload):
        raise AgentInvocationError(
            "provider timeout",
            partial_output='{"partial": true}',
            event_count=2,
        )

    monkeypatch.setattr(case["module"], case["invoke_name"], fake_invoke)

    result = await case["run"](case["state_factory"](), **case["kwargs_factory"]())
    assert result["success"] is False
    assert result["failure_stage"] == "invocation_exception"
    assert result["failure_artifact_id"] is not None
    assert result["raw_output_preview"] == '{"partial": true}'

    artifact = failure_artifacts.read_failure_artifact(result["failure_artifact_id"])
    assert artifact is not None
    assert artifact["phase"] == case["phase"]
    assert artifact["raw_output"] == '{"partial": true}'
