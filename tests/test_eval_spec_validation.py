import time

import pytest

from scripts import eval_spec_validation as eval_script


def test_parse_modes_all():
    assert eval_script.parse_modes("all") == list(eval_script.VALID_MODES)


def test_parse_modes_csv():
    assert eval_script.parse_modes("deterministic,llm") == ["deterministic", "llm"]


def test_parse_modes_invalid():
    with pytest.raises(ValueError):
        eval_script.parse_modes("deterministic,foo")


def test_extract_reason_codes():
    result = {"failures": [{"rule": "RULE_A"}, {"rule": "RULE_B"}, {"other": "ignore"}]}
    assert eval_script._extract_reason_codes(result) == ["RULE_A", "RULE_B"]


def test_classify_row_error():
    assert eval_script._classify_row_error({}) == "semantic"
    assert (
        eval_script._classify_row_error({"failures": [{"message": "execution failed"}]})
        == "provider_error"
    )
    assert (
        eval_script._classify_row_error({"failures": [{"message": "litellm.APIError"}]})
        == "provider_error"
    )


def test_confusion_from_rows():
    rows = [
        {"expected_pass": True, "predicted_fail": False},  # TN
        {"expected_pass": False, "predicted_fail": True},  # TP
        {"expected_pass": True, "predicted_fail": True},  # FP
        {"expected_pass": False, "predicted_fail": False},  # FN
    ]
    cm = eval_script._confusion_from_rows(rows)
    assert cm == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}


def test_compute_mode_metrics_basic():
    # 2 cases
    rows = [
        {
            "case_id": "c1",
            "expected_pass": True,
            "predicted_fail": False,
            "latency_ms": 10,
            "expected_fail_reasons": [],
            "predicted_reason_codes": [],
            "error_class": "semantic",
        },
        {
            "case_id": "c2",
            "expected_pass": False,
            "predicted_fail": True,
            "latency_ms": 20,
            "expected_fail_reasons": ["R1"],
            "predicted_reason_codes": ["R1"],
            "error_class": "semantic",
        },
    ]
    metrics = eval_script._compute_mode_metrics(rows)
    assert metrics["num_cases"] == 2
    assert metrics["confusion_matrix_fail_class"]["tp"] == 1
    assert metrics["confusion_matrix_fail_class"]["tn"] == 1
    assert metrics["accuracy"] == 1.0
    assert metrics["reason_recall_macro"] == 1.0


def test_compute_mode_metrics_over_flagging():
    rows = [
        {
            "case_id": "c1",
            "expected_pass": False,
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


def test_bootstrap_ci_shape():
    # Valid input
    values = [1.0, 0.0, 1.0, 0.0] * 10
    ci = eval_script._bootstrap_ci(values, n_resamples=100)
    assert isinstance(ci, tuple)
    assert len(ci) == 2
    assert 0.0 <= ci[0] <= ci[1] <= 1.0

    # Empty input
    assert eval_script._bootstrap_ci([], n_resamples=10) is None


def test_stratified_sampling():
    cases = [
        {"case_id": "p1", "expected_pass": True},
        {"case_id": "p2", "expected_pass": True},
        {"case_id": "f1", "expected_pass": False},
        {"case_id": "f2", "expected_pass": False},
    ]
    # Limit 2, stratify=True -> Should get 1 pass, 1 fail
    limited = eval_script._limit_cases(cases, limit=2, stratify=True, seed=42)
    assert len(limited) == 2
    pass_count = sum(1 for c in limited if c["expected_pass"])
    fail_count = sum(1 for c in limited if not c["expected_pass"])
    assert pass_count == 1
    assert fail_count == 1


def test_validate_min_positive_cases_errors():
    cases = [
        {"case_id": "f1", "expected_pass": False},
        {"case_id": "f2", "expected_pass": False},
    ]
    # Require 1 positive, have 0 -> Should exit
    with pytest.raises(SystemExit):
        eval_script._validate_min_positive_cases(cases, min_positive_cases=1)

    # Require 0 -> OK
    eval_script._validate_min_positive_cases(cases, min_positive_cases=0)


def test_disagreement_computation():
    rows = [
        {"case_id": "c1", "mode": "deterministic", "predicted_pass": True},
        {"case_id": "c1", "mode": "llm", "predicted_pass": False},
        {"case_id": "c1", "mode": "hybrid", "predicted_pass": True},
        {"case_id": "c2", "mode": "deterministic", "predicted_pass": True},
        {"case_id": "c2", "mode": "llm", "predicted_pass": True},
        {"case_id": "c2", "mode": "hybrid", "predicted_pass": True},
    ]
    disagreements = eval_script._compute_disagreements(rows)

    assert "c1" in disagreements["deterministic_vs_llm"]
    assert "c1" in disagreements["llm_vs_hybrid"]
    assert "c1" not in disagreements["deterministic_vs_hybrid"]
    assert "c2" not in disagreements["deterministic_vs_llm"]


def test_evaluate_cases_uses_stubbed_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        {
            "case_id": "c1",
            "story_id": 10,
            "spec_version_id": 1,
            "expected_pass": True,
            "expected_fail_reasons": [],
            "notes": None,
            "tags": [],
            "enabled": True,
        }
    ]

    def _fake_run(case, mode, consensus_runs):  # Added consensus_runs
        return {
            "case_id": case["case_id"],
            "mode": mode,
            "story_id": case["story_id"],
            "spec_version_id": case["spec_version_id"],
            "expected_pass": case["expected_pass"],
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
    cases = [
        {
            "case_id": "c1",
            "story_id": 10,
            "spec_version_id": 1,
            "expected_pass": True,
            "expected_fail_reasons": [],
        },
        {
            "case_id": "c2",
            "story_id": 11,
            "spec_version_id": 1,
            "expected_pass": False,
            "expected_fail_reasons": ["RULE_X"],
        },
    ]

    delays = {
        ("c1", "deterministic"): 0.04,
        ("c1", "llm"): 0.03,
        ("c2", "deterministic"): 0.02,
        ("c2", "llm"): 0.01,
    }

    def _fake_run(case, mode, consensus_runs):
        time.sleep(delays[(case["case_id"], mode)])
        predicted_fail = case["case_id"] == "c2" and mode == "llm"
        return {
            "case_id": case["case_id"],
            "mode": mode,
            "story_id": case["story_id"],
            "spec_version_id": case["spec_version_id"],
            "expected_pass": case["expected_pass"],
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
    calls = {"count": 0}
    sleep_calls = []

    def _fake_validate(params, tool_context=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("429 too many requests")
        return {"success": True, "passed": True, "failures": []}

    monkeypatch.setattr(
        eval_script, "validate_story_with_spec_authority", _fake_validate
    )
    monkeypatch.setattr(eval_script.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(
        eval_script.time, "sleep", lambda seconds: sleep_calls.append(seconds)
    )

    case = {
        "case_id": "c1",
        "story_id": 10,
        "spec_version_id": 1,
        "expected_pass": True,
        "expected_fail_reasons": [],
    }
    row = eval_script._run_case_mode(case, "llm", consensus_runs=1)

    assert calls["count"] == 3
    assert sleep_calls == [1.0, 2.0]
    assert row["success"] is True
    assert row["predicted_pass"] is True


def test_run_case_mode_does_not_retry_non_retryable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    sleep_calls = []

    def _fake_validate(params, tool_context=None):
        calls["count"] += 1
        raise RuntimeError("schema mismatch")

    monkeypatch.setattr(
        eval_script, "validate_story_with_spec_authority", _fake_validate
    )
    monkeypatch.setattr(
        eval_script.time, "sleep", lambda seconds: sleep_calls.append(seconds)
    )

    case = {
        "case_id": "c1",
        "story_id": 10,
        "spec_version_id": 1,
        "expected_pass": False,
        "expected_fail_reasons": ["RULE_Y"],
    }
    row = eval_script._run_case_mode(case, "llm", consensus_runs=1)

    assert calls["count"] == 1
    assert sleep_calls == []
    assert row["success"] is False
    assert row["error_class"] == "execution_error"
