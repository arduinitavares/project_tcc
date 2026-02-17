
import pytest
from unittest.mock import MagicMock
from scripts import eval_spec_validation as eval_script

def test_parse_modes_all():
    assert eval_script.parse_modes("all") == list(eval_script.VALID_MODES)

def test_parse_modes_csv():
    assert eval_script.parse_modes("deterministic,llm") == ["deterministic", "llm"]

def test_parse_modes_invalid():
    with pytest.raises(ValueError):
        eval_script.parse_modes("deterministic,foo")

def test_extract_reason_codes():
    result = {
        "failures": [
            {"rule": "RULE_A"},
            {"rule": "RULE_B"},
            {"other": "ignore"}
        ]
    }
    assert eval_script._extract_reason_codes(result) == ["RULE_A", "RULE_B"]

def test_classify_row_error():
    assert eval_script._classify_row_error({}) == "semantic"
    assert eval_script._classify_row_error({"failures": [{"message": "execution failed"}]}) == "provider_error"

def test_confusion_from_rows():
    rows = [
        # {"expected_pass": True, "predicted_fail": False}, # TN (fail=false, pass=true) -> No, TN is expected_fail=False and predicted_fail=False
        # Removing the first duplicate TN to make the test match expected counts
        # Logic in script:
        # expected_fail = not expected_pass
        # tp: exp_fail and pred_fail
        # fp: not exp_fail and pred_fail
        # tn: not exp_fail and not pred_fail
        # fn: exp_fail and not pred_fail

        {"expected_pass": True, "predicted_fail": False}, # TN
        {"expected_pass": False, "predicted_fail": True}, # TP
        {"expected_pass": True, "predicted_fail": True},  # FP
        {"expected_pass": False, "predicted_fail": False}, # FN
    ]
    cm = eval_script._confusion_from_rows(rows)
    assert cm == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}

def test_compute_mode_metrics():
    # 2 cases
    rows = [
        {
            "case_id": "c1",
            "expected_pass": True,
            "predicted_fail": False,
            "latency_ms": 10,
            "expected_fail_reasons": [],
            "predicted_reason_codes": [],
            "error_class": "semantic"
        },
        {
            "case_id": "c2",
            "expected_pass": False,
            "predicted_fail": True,
            "latency_ms": 20,
            "expected_fail_reasons": ["R1"],
            "predicted_reason_codes": ["R1"],
            "error_class": "semantic"
        }
    ]
    metrics = eval_script._compute_mode_metrics(rows)
    assert metrics["num_cases"] == 2
    assert metrics["confusion_matrix_fail_class"]["tp"] == 1
    assert metrics["confusion_matrix_fail_class"]["tn"] == 1
    assert metrics["accuracy"] == 1.0
    assert metrics["reason_recall_macro"] == 1.0

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

    def _fake_run(case, mode, consensus_runs): # Added consensus_runs
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
    # The regression test in question calls this without consensus_runs
    # But we modified the signature.
    # If the signature of evaluate_cases was evaluate_cases(cases, modes, consensus_runs=1),
    # this call would work.
    # The test failure shows: evaluate_cases(cases, ["deterministic", "llm"])
    # So we need to ensure evaluate_cases has a default.
    evaluated = eval_script.evaluate_cases(cases, ["deterministic", "llm"])

    assert "deterministic" in evaluated["mode_metrics"]
    assert "llm" in evaluated["mode_metrics"]
