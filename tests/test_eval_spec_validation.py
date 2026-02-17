from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import eval_spec_validation as eval_script


def test_parse_modes_all_and_explicit() -> None:
    assert eval_script.parse_modes("all") == ["deterministic", "llm", "hybrid"]
    assert eval_script.parse_modes("deterministic,llm") == ["deterministic", "llm"]


def test_parse_modes_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        eval_script.parse_modes("invalid")


def test_compute_mode_metrics_confusion_matrix() -> None:
    records = [
        # TP: expected fail, predicted fail
        {
            "expected_pass": False,
            "predicted_fail": True,
            "predicted_reason_codes": ["RULE_X"],
            "expected_fail_reasons": ["RULE_X"],
            "latency_ms": 10.0,
        },
        # FP: expected pass, predicted fail
        {
            "expected_pass": True,
            "predicted_fail": True,
            "predicted_reason_codes": ["RULE_X"],
            "expected_fail_reasons": [],
            "latency_ms": 20.0,
        },
        # TN: expected pass, predicted pass
        {
            "expected_pass": True,
            "predicted_fail": False,
            "predicted_reason_codes": [],
            "expected_fail_reasons": [],
            "latency_ms": 30.0,
        },
        # FN: expected fail, predicted pass
        {
            "expected_pass": False,
            "predicted_fail": False,
            "predicted_reason_codes": [],
            "expected_fail_reasons": ["RULE_Y"],
            "latency_ms": 40.0,
        },
    ]
    metrics = eval_script._compute_mode_metrics(records)  # pylint: disable=protected-access
    cm = metrics["confusion_matrix_fail_class"]
    assert cm == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert metrics["num_labeled_cases"] == 4
    assert metrics["accuracy"] == 0.5


def test_compute_mode_metrics_reason_precision_and_over_flagging() -> None:
    records = [
        {
            "expected_pass": False,
            "predicted_fail": True,
            "predicted_reason_codes": ["RULE_A", "RULE_B", "RULE_C"],
            "expected_fail_reasons": ["RULE_A"],
            "latency_ms": 10.0,
        }
    ]
    metrics = eval_script._compute_mode_metrics(records)  # pylint: disable=protected-access
    assert metrics["reason_recall_macro"] == 1.0
    assert metrics["reason_precision_macro"] == pytest.approx(1.0 / 3.0)
    assert metrics["over_flagging_rate"] == 1.0


def test_classify_provider_error_detects_credits() -> None:
    result = {
        "failures": [
            {
                "rule": "RULE_LLM_SPEC_VALIDATION",
                "actual": "Provider requires more credits to continue",
                "message": "LLM validation execution failed",
            }
        ]
    }
    assert eval_script._classify_row_error(result) == "provider_error"  # pylint: disable=protected-access


def test_classify_provider_error_detects_truncation() -> None:
    result = {
        "failures": [
            {
                "rule": "RULE_LLM_SPEC_VALIDATION",
                "actual": "EOF while parsing a value",
                "message": "LLM validation execution failed",
            }
        ]
    }
    assert eval_script._classify_row_error(result) == "provider_error"  # pylint: disable=protected-access


def test_classify_provider_error_detects_no_response() -> None:
    result = {
        "failures": [
            {
                "rule": "RULE_LLM_SPEC_VALIDATION",
                "actual": "Spec validator agent returned no text response",
                "message": "LLM validation execution failed",
            }
        ]
    }
    assert eval_script._classify_row_error(result) == "provider_error"  # pylint: disable=protected-access


def test_classify_semantic_not_flagged() -> None:
    result = {
        "failures": [
            {
                "rule": "RULE_LLM_SPEC_VALIDATION",
                "actual": "Missing in-scope requirement",
                "message": "Story not compliant with invariant INV-abc",
            }
        ]
    }
    assert eval_script._classify_row_error(result) == "semantic"  # pylint: disable=protected-access


def test_compute_mode_metrics_separates_clean_and_raw() -> None:
    records = [
        {
            "expected_pass": False,
            "predicted_fail": True,
            "predicted_reason_codes": ["RULE_LLM_SPEC_VALIDATION"],
            "expected_fail_reasons": ["RULE_LLM_SPEC_VALIDATION"],
            "error_class": "semantic",
            "latency_ms": 100.0,
        },
        {
            "expected_pass": True,
            "predicted_fail": True,
            "predicted_reason_codes": ["RULE_LLM_SPEC_VALIDATION"],
            "expected_fail_reasons": [],
            "error_class": "provider_error",
            "latency_ms": 120.0,
        },
    ]
    metrics = eval_script._compute_mode_metrics(records)  # pylint: disable=protected-access
    assert metrics["provider_error_count"] == 1
    assert metrics["clean_cases"] == 1
    assert metrics["accuracy"] == 0.5
    assert metrics["clean_accuracy"] == 1.0


def test_bootstrap_ci_returns_tuple() -> None:
    ci = eval_script._bootstrap_ci([0.1, 0.2, 0.3, 0.4], n_resamples=200, seed=1)  # pylint: disable=protected-access
    assert ci is not None
    assert ci[0] <= ci[1]


def test_compute_disagreements() -> None:
    raw = [
        {"case_id": "c1", "mode": "deterministic", "predicted_pass": True},
        {"case_id": "c1", "mode": "llm", "predicted_pass": False},
        {"case_id": "c1", "mode": "hybrid", "predicted_pass": False},
        {"case_id": "c2", "mode": "deterministic", "predicted_pass": True},
        {"case_id": "c2", "mode": "llm", "predicted_pass": True},
        {"case_id": "c2", "mode": "hybrid", "predicted_pass": True},
    ]
    disagreements = eval_script._compute_disagreements(raw)  # pylint: disable=protected-access
    assert "c1" in disagreements["deterministic_vs_llm"]
    assert "c1" in disagreements["deterministic_vs_hybrid"]
    assert disagreements["llm_vs_hybrid"] == []


def test_read_cases_respects_enabled_flag(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "a",
                        "story_id": 1,
                        "spec_version_id": 2,
                        "enabled": True,
                    }
                ),
                json.dumps(
                    {
                        "case_id": "b",
                        "story_id": 2,
                        "spec_version_id": 2,
                        "enabled": False,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cases_default = eval_script._read_cases(cases_path, include_disabled=False)  # pylint: disable=protected-access
    cases_all = eval_script._read_cases(cases_path, include_disabled=True)  # pylint: disable=protected-access
    assert len(cases_default) == 1
    assert len(cases_all) == 2


def test_limit_cases_stratified_balances_classes() -> None:
    cases = []
    for idx in range(80):
        cases.append(
            {
                "case_id": f"f-{idx}",
                "story_id": idx,
                "spec_version_id": 1,
                "expected_pass": False,
            }
        )
    for idx in range(20):
        cases.append(
            {
                "case_id": f"p-{idx}",
                "story_id": 100 + idx,
                "spec_version_id": 1,
                "expected_pass": True,
            }
        )
    selected = eval_script._limit_cases(  # pylint: disable=protected-access
        cases, limit=10, stratify=True, seed=7
    )
    positives = sum(1 for c in selected if c.get("expected_pass") is True)
    assert positives >= 2


def test_validate_min_positive_cases_errors() -> None:
    cases = [
        {"expected_pass": False},
        {"expected_pass": False},
    ]
    with pytest.raises(SystemExit):
        eval_script._validate_min_positive_cases(  # pylint: disable=protected-access
            cases, min_positive_cases=1
        )


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

    def _fake_run(case, mode):
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
            "predicted_reason_codes": ["RULE_LLM_SPEC_VALIDATION"] if mode == "llm" else [],
            "latency_ms": 5.0,
            "result": {"success": True, "passed": mode != "llm"},
        }

    monkeypatch.setattr(eval_script, "_run_case_mode", _fake_run)
    evaluated = eval_script.evaluate_cases(cases, ["deterministic", "llm"])
    assert len(evaluated["raw_rows"]) == 2
    assert evaluated["mode_metrics"]["deterministic"]["num_cases"] == 1
    assert evaluated["mode_metrics"]["llm"]["num_cases"] == 1
