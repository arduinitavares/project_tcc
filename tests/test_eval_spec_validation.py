"""Tests for eval spec validation."""

import time
from typing import Any, Never

import pytest

from scripts import eval_spec_validation as eval_script

JsonDict = dict[str, Any]
EXPECTED_OUTCOME_FIELD = "expected_pass"
PREDICTED_OUTCOME_FIELD = "predicted_pass"


def test_parse_modes_all() -> None:
    """Verify parse modes all."""
    assert eval_script.parse_modes("all") == list(eval_script.VALID_MODES)


def test_parse_modes_csv() -> None:
    """Verify parse modes csv."""
    assert eval_script.parse_modes("deterministic,llm") == ["deterministic", "llm"]


def test_parse_modes_invalid() -> None:
    """Verify parse modes invalid."""
    with pytest.raises(ValueError):  # noqa: PT011
        eval_script.parse_modes("deterministic,foo")


def test_extract_reason_codes() -> None:
    """Verify extract reason codes."""
    result = {"failures": [{"rule": "RULE_A"}, {"rule": "RULE_B"}, {"other": "ignore"}]}
    assert eval_script._extract_reason_codes(result) == ["RULE_A", "RULE_B"]


def test_classify_row_error() -> None:
    """Verify classify row error."""
    assert eval_script._classify_row_error({}) == "semantic"
    assert (
        eval_script._classify_row_error({"failures": [{"message": "execution failed"}]})
        == "provider_error"
    )
    assert (
        eval_script._classify_row_error({"failures": [{"message": "litellm.APIError"}]})
        == "provider_error"
    )


def test_confusion_from_rows() -> None:
    """Verify confusion from rows."""
    rows = [
        {EXPECTED_OUTCOME_FIELD: True, "predicted_fail": False},  # TN
        {EXPECTED_OUTCOME_FIELD: False, "predicted_fail": True},  # TP
        {EXPECTED_OUTCOME_FIELD: True, "predicted_fail": True},  # FP
        {EXPECTED_OUTCOME_FIELD: False, "predicted_fail": False},  # FN
    ]
    cm = eval_script._confusion_from_rows(rows)
    assert cm == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}


def test_compute_mode_metrics_basic() -> None:
    # 2 cases
    """Verify compute mode metrics basic."""
    rows = [
        {
            "case_id": "c1",
            EXPECTED_OUTCOME_FIELD: True,
            "predicted_fail": False,
            "latency_ms": 10,
            "expected_fail_reasons": [],
            "predicted_reason_codes": [],
            "error_class": "semantic",
        },
        {
            "case_id": "c2",
            EXPECTED_OUTCOME_FIELD: False,
            "predicted_fail": True,
            "latency_ms": 20,
            "expected_fail_reasons": ["R1"],
            "predicted_reason_codes": ["R1"],
            "error_class": "semantic",
        },
    ]
    metrics = eval_script._compute_mode_metrics(rows)
    assert metrics["num_cases"] == 2  # noqa: PLR2004
    assert metrics["confusion_matrix_fail_class"]["tp"] == 1
    assert metrics["confusion_matrix_fail_class"]["tn"] == 1
    assert metrics["accuracy"] == 1.0
    assert metrics["reason_recall_macro"] == 1.0


def test_compute_mode_metrics_over_flagging() -> None:
    """Verify compute mode metrics over flagging."""
    rows = [
        {
            "case_id": "c1",
            EXPECTED_OUTCOME_FIELD: False,
            "predicted_fail": True,
            "latency_ms": 10,
            "expected_fail_reasons": ["R1"],
            "predicted_reason_codes": [
                "R1",
                "R2",
                "R3",
            ],  # 3 > 2*1, should trigger over-flagging
            "error_class": "semantic",
        }
    ]
    metrics = eval_script._compute_mode_metrics(rows)
    assert metrics["over_flagging_rate"] == 1.0
    assert metrics["reason_precision_macro"] == 1 / 3


def test_bootstrap_ci_shape() -> None:
    # Valid input
    """Verify bootstrap ci shape."""
    values = [1.0, 0.0, 1.0, 0.0] * 10
    ci = eval_script._bootstrap_ci(values, n_resamples=100)
    assert isinstance(ci, tuple)
    assert len(ci) == 2  # noqa: PLR2004
    assert 0.0 <= ci[0] <= ci[1] <= 1.0

    # Empty input
    assert eval_script._bootstrap_ci([], n_resamples=10) is None


def test_stratified_sampling() -> None:
    """Verify stratified sampling."""
    cases: list[JsonDict] = [
        {"case_id": "p1", EXPECTED_OUTCOME_FIELD: True},
        {"case_id": "p2", EXPECTED_OUTCOME_FIELD: True},
        {"case_id": "f1", EXPECTED_OUTCOME_FIELD: False},
        {"case_id": "f2", EXPECTED_OUTCOME_FIELD: False},
    ]
    # Limit 2, stratify=True -> Should get 1 pass, 1 fail
    limited = eval_script._limit_cases(cases, limit=2, stratify=True, seed=42)
    assert len(limited) == 2  # noqa: PLR2004
    pass_count = sum(1 for c in limited if c[EXPECTED_OUTCOME_FIELD])
    fail_count = sum(1 for c in limited if not c[EXPECTED_OUTCOME_FIELD])
    assert pass_count == 1
    assert fail_count == 1


def test_validate_min_positive_cases_errors() -> None:
    """Verify validate min positive cases errors."""
    cases = [
        {"case_id": "f1", EXPECTED_OUTCOME_FIELD: False},
        {"case_id": "f2", EXPECTED_OUTCOME_FIELD: False},
    ]
    # Require 1 positive, have 0 -> Should exit
    with pytest.raises(SystemExit):
        eval_script._validate_min_positive_cases(cases, min_positive_cases=1)

    # Require 0 -> OK
    eval_script._validate_min_positive_cases(cases, min_positive_cases=0)


def test_disagreement_computation() -> None:
    """Verify disagreement computation."""
    rows = [
        {"case_id": "c1", "mode": "deterministic", PREDICTED_OUTCOME_FIELD: True},
        {"case_id": "c1", "mode": "llm", PREDICTED_OUTCOME_FIELD: False},
        {"case_id": "c1", "mode": "hybrid", PREDICTED_OUTCOME_FIELD: True},
        {"case_id": "c2", "mode": "deterministic", PREDICTED_OUTCOME_FIELD: True},
        {"case_id": "c2", "mode": "llm", PREDICTED_OUTCOME_FIELD: True},
        {"case_id": "c2", "mode": "hybrid", PREDICTED_OUTCOME_FIELD: True},
    ]
    disagreements = eval_script._compute_disagreements(rows)

    assert "c1" in disagreements["deterministic_vs_llm"]
    assert "c1" in disagreements["llm_vs_hybrid"]
    assert "c1" not in disagreements["deterministic_vs_hybrid"]
    assert "c2" not in disagreements["deterministic_vs_llm"]


def test_evaluate_cases_uses_stubbed_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify evaluate cases uses stubbed runner."""
    cases = [
        {
            "case_id": "c1",
            "story_id": 10,
            "spec_version_id": 1,
            EXPECTED_OUTCOME_FIELD: True,
            "expected_fail_reasons": [],
            "notes": None,
            "tags": [],
            "enabled": True,
        }
    ]

    def _fake_run(
        case: JsonDict, mode: str, consensus_runs: int
    ) -> JsonDict:  # Added consensus_runs
        del consensus_runs
        return {
            "case_id": case["case_id"],
            "mode": mode,
            "story_id": case["story_id"],
            "spec_version_id": case["spec_version_id"],
            EXPECTED_OUTCOME_FIELD: case[EXPECTED_OUTCOME_FIELD],
            "expected_fail_reasons": case["expected_fail_reasons"],
            "success": True,
            "predicted_pass": mode != "llm",
            "predicted_fail": mode == "llm",
            "predicted_reason_codes": ["RULE_LLM_SPEC_VALIDATION"]
            if mode == "llm"
            else [],
            "latency_ms": 5.0,
            "result": {"success": True, "passed": mode != "llm"},
        }

    monkeypatch.setattr(eval_script, "_run_case_mode", _fake_run)

    # Verify backward compatibility (no consensus arg)
    evaluated = eval_script.evaluate_cases(cases, ["deterministic", "llm"])
    assert "deterministic" in evaluated["mode_metrics"]
    assert "llm" in evaluated["mode_metrics"]

    # Verify consensus arg passing
    evaluated_consensus = eval_script.evaluate_cases(
        cases, ["deterministic"], consensus_runs=3
    )
    assert "deterministic" in evaluated_consensus["mode_metrics"]

    # Verify async concurrency path
    evaluated_parallel = eval_script.evaluate_cases(
        cases,
        ["deterministic", "llm"],
        consensus_runs=1,
        max_concurrency=2,
    )
    assert "deterministic" in evaluated_parallel["mode_metrics"]
    assert "llm" in evaluated_parallel["mode_metrics"]


def test_evaluate_cases_async_path_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify evaluate cases async path preserves order."""
    cases: list[JsonDict] = [
        {
            "case_id": "c1",
            "story_id": 10,
            "spec_version_id": 1,
            EXPECTED_OUTCOME_FIELD: True,
            "expected_fail_reasons": [],
        },
        {
            "case_id": "c2",
            "story_id": 11,
            "spec_version_id": 1,
            EXPECTED_OUTCOME_FIELD: False,
            "expected_fail_reasons": ["RULE_X"],
        },
    ]

    delays: dict[tuple[str, str], float] = {
        ("c1", "deterministic"): 0.04,
        ("c1", "llm"): 0.03,
        ("c2", "deterministic"): 0.02,
        ("c2", "llm"): 0.01,
    }

    def _fake_run(case: JsonDict, mode: str, consensus_runs: int) -> JsonDict:
        del consensus_runs
        case_id = str(case["case_id"])
        time.sleep(delays[(case_id, mode)])
        predicted_fail = case["case_id"] == "c2" and mode == "llm"
        return {
            "case_id": case["case_id"],
            "mode": mode,
            "story_id": case["story_id"],
            "spec_version_id": case["spec_version_id"],
            EXPECTED_OUTCOME_FIELD: case[EXPECTED_OUTCOME_FIELD],
            "expected_fail_reasons": case["expected_fail_reasons"],
            "success": True,
            "predicted_pass": not predicted_fail,
            "predicted_fail": predicted_fail,
            "predicted_reason_codes": ["RULE_X"] if predicted_fail else [],
            "error_class": "semantic",
            "latency_ms": 1.0,
            "result": {"success": True, "passed": not predicted_fail},
        }

    monkeypatch.setattr(eval_script, "_run_case_mode", _fake_run)

    evaluated = eval_script.evaluate_cases(
        cases,
        ["deterministic", "llm"],
        consensus_runs=1,
        max_concurrency=2,
    )

    ordered_pairs = [(row["case_id"], row["mode"]) for row in evaluated["raw_rows"]]
    assert ordered_pairs == [
        ("c1", "deterministic"),
        ("c1", "llm"),
        ("c2", "deterministic"),
        ("c2", "llm"),
    ]


def test_run_case_mode_retries_retryable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify run case mode retries retryable errors."""
    calls = {"count": 0}
    sleep_calls = []

    def _fake_validate(params: object, tool_context: object = None) -> object:
        del params, tool_context
        calls["count"] += 1
        if calls["count"] < 3:  # noqa: PLR2004
            msg = "429 too many requests"
            raise RuntimeError(msg)
        return {"success": True, "passed": True, "failures": []}

    monkeypatch.setattr(
        eval_script, "validate_story_with_spec_authority", _fake_validate
    )
    monkeypatch.setattr(eval_script, "_retry_jitter_seconds", lambda: 0.0)
    monkeypatch.setattr(eval_script.time, "sleep", sleep_calls.append)

    case = {
        "case_id": "c1",
        "story_id": 10,
        "spec_version_id": 1,
        EXPECTED_OUTCOME_FIELD: True,
        "expected_fail_reasons": [],
    }
    row = eval_script._run_case_mode(case, "llm", consensus_runs=1)

    assert calls["count"] == 3  # noqa: PLR2004
    assert sleep_calls == [1.0, 2.0]
    assert row["success"] is True
    assert row["predicted_pass"] is True


def test_run_case_mode_does_not_retry_non_retryable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify run case mode does not retry non retryable errors."""
    calls = {"count": 0}
    sleep_calls = []

    def _fake_validate(params: object, tool_context: object = None) -> Never:
        del params, tool_context
        calls["count"] += 1
        msg = "schema mismatch"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        eval_script, "validate_story_with_spec_authority", _fake_validate
    )
    monkeypatch.setattr(eval_script.time, "sleep", sleep_calls.append)

    case = {
        "case_id": "c1",
        "story_id": 10,
        "spec_version_id": 1,
        EXPECTED_OUTCOME_FIELD: False,
        "expected_fail_reasons": ["RULE_Y"],
    }
    row = eval_script._run_case_mode(case, "llm", consensus_runs=1)

    assert calls["count"] == 1
    assert sleep_calls == []
    assert row["success"] is False
    assert row["error_class"] == "execution_error"
