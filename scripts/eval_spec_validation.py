#!/usr/bin/env python3
"""Evaluate story validation quality across deterministic/llm/hybrid modes with consensus logic."""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from tools.spec_tools import validate_story_with_spec_authority  # pylint: disable=wrong-import-position


ValidationMode = str
VALID_MODES: Tuple[ValidationMode, ...] = ("deterministic", "llm", "hybrid")
LOGGER = logging.getLogger(__name__)
BRANCH_LOG_LIMIT = 20
_BRANCH_LOG_COUNTS: Dict[str, int] = {}
_BRANCH_LOG_SUPPRESSED: set[str] = set()
_PROVIDER_ERROR_PATTERNS: Tuple[str, ...] = (
    "requires more credits",
    "eof while parsing",
    "returned no text response",
    "execution failed",
    "litellm.apierror",
    "openrouterexception",
)


def _branch(name: str, condition: bool, when_true: str, when_false: str) -> bool:
    count = _BRANCH_LOG_COUNTS.get(name, 0) + 1
    _BRANCH_LOG_COUNTS[name] = count
    if count <= BRANCH_LOG_LIMIT:
        if condition:
            LOGGER.debug("[if:%s] TRUE - %s", name, when_true)
        else:
            LOGGER.debug("[if:%s] FALSE - %s", name, when_false)
    elif name not in _BRANCH_LOG_SUPPRESSED:
        _BRANCH_LOG_SUPPRESSED.add(name)
        LOGGER.debug(
            "[if:%s] log limit reached; suppressing further repeats (limit=%d)",
            name,
            BRANCH_LOG_LIMIT,
        )
    if condition:
        return True
    else:
        return False


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    LOGGER.info("Reading JSONL: %s", path)
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            line = line.strip()
            if _branch(
                "read_jsonl.empty_line",
                not line,
                f"Skipping empty line {idx}",
                f"Parsing line {idx}",
            ):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {idx} of {path}") from exc
            rows.append(row)
    LOGGER.info("Loaded %d row(s) from %s", len(rows), path)
    return rows


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    LOGGER.info("Writing JSONL: %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    LOGGER.info("Finished writing JSONL: %s", path)


def _read_cases(path: Path, include_disabled: bool) -> List[Dict[str, Any]]:
    LOGGER.info("Normalizing benchmark cases from %s (include_disabled=%s)", path, include_disabled)
    cases = _read_jsonl(path)
    normalized: List[Dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        case_id = case.get("case_id") or f"case-{idx}"
        enabled = case.get("enabled", True)
        if _branch(
            "read_cases.skip_disabled",
            (not include_disabled and enabled is False),
            f"Skipping disabled case_id={case_id}",
            f"Keeping case_id={case_id}",
        ):
            continue
        story_id = case.get("story_id")
        spec_version_id = case.get("spec_version_id")
        if _branch(
            "read_cases.invalid_story_or_spec",
            (not isinstance(story_id, int) or not isinstance(spec_version_id, int)),
            f"Invalid IDs for case_id={case_id}; raising",
            f"Valid IDs for case_id={case_id}",
        ):
            raise ValueError(
                f"Case {case_id} must include integer story_id and spec_version_id"
            )
        expected_pass = case.get("expected_pass")
        if _branch(
            "read_cases.expected_pass_not_bool",
            not isinstance(expected_pass, bool),
            f"case_id={case_id} expected_pass is unlabeled",
            f"case_id={case_id} expected_pass is labeled",
        ):
            expected_pass = None
        expected_fail_reasons = case.get("expected_fail_reasons") or []
        if _branch(
            "read_cases.expected_fail_reasons_not_list",
            not isinstance(expected_fail_reasons, list),
            f"case_id={case_id} fail reasons not list; defaulting to []",
            f"case_id={case_id} fail reasons list accepted",
        ):
            expected_fail_reasons = []
        expected_fail_reasons = [str(v) for v in expected_fail_reasons]

        normalized.append(
            {
                "case_id": str(case_id),
                "story_id": story_id,
                "spec_version_id": spec_version_id,
                "expected_pass": expected_pass,
                "expected_fail_reasons": expected_fail_reasons,
                "notes": case.get("notes"),
                "tags": case.get("tags") if isinstance(case.get("tags"), list) else [],
                "enabled": bool(enabled),
                "label_source": case.get("label_source")
            }
        )
    LOGGER.info("Prepared %d normalized case(s)", len(normalized))
    return normalized


def _extract_reason_codes(result: Dict[str, Any]) -> List[str]:
    codes = set()
    for failure in result.get("failures", []):
        if _branch(
            "extract_reason_codes.failure_is_dict",
            isinstance(failure, dict),
            "Failure entry is dict",
            "Failure entry ignored (non-dict)",
        ):
            rule = failure.get("rule")
            if _branch(
                "extract_reason_codes.rule_is_nonempty_str",
                isinstance(rule, str) and bool(rule.strip()),
                f"Recording rule={rule!r}",
                f"Ignoring invalid/empty rule={rule!r}",
            ):
                codes.add(rule.strip())
    return sorted(codes)


def _classify_row_error(result: Dict[str, Any]) -> str:
    """Classify a validation result as provider_error or semantic."""
    failures = result.get("failures", [])
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        text = (
            f"{failure.get('actual', '')} {failure.get('message', '')}"
        ).lower()
        if any(pattern in text for pattern in _PROVIDER_ERROR_PATTERNS):
            return "provider_error"
    return "semantic"


def _safe_mean(values: Sequence[float]) -> Optional[float]:
    if _branch(
        "safe_mean.empty_values",
        not values,
        "Returning None for empty mean input",
        f"Computing mean over n={len(values)}",
    ):
        return None
    return float(sum(values) / len(values))


def _safe_median(values: Sequence[float]) -> Optional[float]:
    if _branch(
        "safe_median.empty_values",
        not values,
        "Returning None for empty median input",
        f"Computing median over n={len(values)}",
    ):
        return None
    return float(statistics.median(values))


def _bootstrap_ci(
    values: Sequence[float],
    *,
    n_resamples: int = 1000,
    seed: int = 42,
) -> Optional[Tuple[float, float]]:
    """Compute bootstrap percentile CI for a list of scalar values."""
    if _branch(
        "bootstrap_ci.empty_values",
        not values,
        "Returning None for empty bootstrap input",
        f"Running bootstrap_ci n={len(values)} resamples={n_resamples} seed={seed}",
    ):
        return None
    rng = random.Random(seed)
    samples: List[float] = []
    value_list = list(values)
    for _ in range(n_resamples):
        sample = [rng.choice(value_list) for _ in range(len(value_list))]
        samples.append(sum(sample) / len(sample))
    samples.sort()
    low_idx = int(0.025 * (len(samples) - 1))
    high_idx = int(0.975 * (len(samples) - 1))
    return samples[low_idx], samples[high_idx]


def _precision(tp: int, fp: int) -> Optional[float]:
    denom = tp + fp
    if _branch(
        "precision.zero_denominator",
        denom == 0,
        f"tp={tp}, fp={fp} -> None",
        f"tp={tp}, fp={fp} -> compute",
    ):
        return None
    return tp / denom


def _recall(tp: int, fn: int) -> Optional[float]:
    denom = tp + fn
    if _branch(
        "recall.zero_denominator",
        denom == 0,
        f"tp={tp}, fn={fn} -> None",
        f"tp={tp}, fn={fn} -> compute",
    ):
        return None
    return tp / denom


def _f1(precision: Optional[float], recall: Optional[float]) -> Optional[float]:
    if _branch(
        "f1.missing_precision_or_recall",
        precision is None or recall is None,
        f"precision={precision}, recall={recall} -> None",
        f"precision={precision}, recall={recall} -> continue",
    ):
        return None
    denom = precision + recall
    if _branch(
        "f1.zero_denominator",
        math.isclose(denom, 0.0),
        "precision+recall ~= 0 -> None",
        "precision+recall valid -> compute",
    ):
        return None
    return 2 * precision * recall / denom


def _fmt_ci(ci: Optional[Tuple[float, float]]) -> str:
    if _branch(
        "fmt_ci.none_ci",
        ci is None,
        "CI missing -> '-'",
        "CI present -> format range",
    ):
        return "-"
    return f"[{ci[0]*100:.1f}%, {ci[1]*100:.1f}%]"


def _confusion_from_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    tp = fp = tn = fn = 0
    for row in rows:
        expected_pass = bool(row["expected_pass"])
        predicted_fail = bool(row["predicted_fail"])
        expected_fail = not expected_pass
        if _branch(
            "confusion.tp",
            expected_fail and predicted_fail,
            f"case contributes TP (expected_fail={expected_fail}, predicted_fail={predicted_fail})",
            "not TP",
        ):
            tp += 1
        elif _branch(
            "confusion.fp",
            (not expected_fail and predicted_fail),
            f"case contributes FP (expected_fail={expected_fail}, predicted_fail={predicted_fail})",
            "not FP",
        ):
            fp += 1
        elif _branch(
            "confusion.tn",
            (not expected_fail and not predicted_fail),
            f"case contributes TN (expected_fail={expected_fail}, predicted_fail={predicted_fail})",
            "not TN",
        ):
            tn += 1
        elif _branch(
            "confusion.fn",
            (expected_fail and not predicted_fail),
            f"case contributes FN (expected_fail={expected_fail}, predicted_fail={predicted_fail})",
            "not FN",
        ):
            fn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def _bootstrap_metric_ci(
    rows: Sequence[Dict[str, Any]],
    metric_name: str,
    *,
    n_resamples: int = 1000,
    seed: int = 42,
) -> Optional[Tuple[float, float]]:
    """Bootstrap CI for confusion-derived metrics."""
    if _branch(
        "bootstrap_metric_ci.empty_rows",
        not rows,
        "No rows -> CI None",
        f"Bootstrapping metric={metric_name} with n={len(rows)}",
    ):
        return None
    rng = random.Random(seed)
    values: List[float] = []
    for _ in range(n_resamples):
        sample = [rng.choice(rows) for _ in range(len(rows))]
        cm = _confusion_from_rows(sample)
        precision = _precision(cm["tp"], cm["fp"])
        recall = _recall(cm["tp"], cm["fn"])
        if _branch(
            "bootstrap_metric_ci.metric_precision_fail",
            metric_name == "precision_fail",
            "Selecting precision metric",
            "Not precision metric",
        ):
            metric = precision
        elif _branch(
            "bootstrap_metric_ci.metric_recall_fail",
            metric_name == "recall_fail",
            "Selecting recall metric",
            "Not recall metric",
        ):
            metric = recall
        elif _branch(
            "bootstrap_metric_ci.metric_f1_fail",
            metric_name == "f1_fail",
            "Selecting f1 metric",
            "Not f1 metric",
        ):
            metric = _f1(precision, recall)
        elif _branch(
            "bootstrap_metric_ci.metric_accuracy",
            metric_name == "accuracy",
            "Selecting accuracy metric",
            "Not accuracy metric",
        ):
            metric = (cm["tp"] + cm["tn"]) / len(sample) if sample else None
        else:
            raise ValueError(f"Unsupported metric for CI: {metric_name}")
        if _branch(
            "bootstrap_metric_ci.metric_not_none",
            metric is not None,
            f"Appending metric value={metric}",
            "Skipping None metric value",
        ):
            values.append(metric)
    return _bootstrap_ci(values, n_resamples=n_resamples, seed=seed)


def _run_case_mode(case: Dict[str, Any], mode: ValidationMode, consensus_runs: int) -> Dict[str, Any]:
    LOGGER.debug(
        "Running validation case_id=%s mode=%s story_id=%s spec_version_id=%s consensus=%d",
        case.get("case_id"),
        mode,
        case.get("story_id"),
        case.get("spec_version_id"),
        consensus_runs,
    )

    runs = []
    total_latency = 0.0

    # Deterministic modes don't need consensus
    if mode == "deterministic":
        actual_runs = 1
    else:
        actual_runs = max(1, consensus_runs)

    for i in range(actual_runs):
        started = time.perf_counter()
        try:
            result = validate_story_with_spec_authority(
                {
                    "story_id": case["story_id"],
                    "spec_version_id": case["spec_version_id"],
                    "mode": mode,
                },
                tool_context=None,
            )
            success = bool(result.get("success"))
            passed = bool(result.get("passed")) if success else False
            reason_codes = _extract_reason_codes(result)
            error_class = _classify_row_error(result)
        except Exception as e:
            LOGGER.error(f"Error in validation run {i+1}: {e}")
            result = {"error": str(e)}
            success = False
            passed = False
            reason_codes = []
            error_class = "execution_error"

        elapsed_ms = (time.perf_counter() - started) * 1000
        total_latency += elapsed_ms

        runs.append({
            "success": success,
            "passed": passed,
            "reason_codes": reason_codes,
            "error_class": error_class,
            "result": result
        })

    # Consensus Logic
    pass_votes = sum(1 for r in runs if r["passed"])
    fail_votes = sum(1 for r in runs if not r["passed"])
    majority_threshold = (actual_runs // 2) + 1

    predicted_pass = pass_votes >= majority_threshold

    # Stability Score: % agreement with majority
    majority_count = pass_votes if predicted_pass else fail_votes
    stability_score = majority_count / actual_runs if actual_runs > 0 else 0.0

    # Merge reason codes from majority runs
    merged_reasons = set()
    for r in runs:
        if r["passed"] == predicted_pass:
            merged_reasons.update(r["reason_codes"])

    # Use first run's error class or result for details, but consensus verdict
    primary_run = runs[0]

    LOGGER.debug(
        "Completed case_id=%s mode=%s success=%s predicted_pass=%s reasons=%s latency_ms=%.2f stability=%.2f",
        case.get("case_id"),
        mode,
        primary_run["success"],
        predicted_pass,
        sorted(merged_reasons),
        total_latency / actual_runs,
        stability_score
    )

    return {
        "case_id": case["case_id"],
        "mode": mode,
        "story_id": case["story_id"],
        "spec_version_id": case["spec_version_id"],
        "expected_pass": case["expected_pass"],
        "expected_fail_reasons": case["expected_fail_reasons"],
        "success": primary_run["success"], # Reporting primary run success status
        "predicted_pass": predicted_pass,
        "predicted_fail": not predicted_pass,
        "predicted_reason_codes": sorted(merged_reasons),
        "error_class": primary_run["error_class"],
        "latency_ms": total_latency / actual_runs,
        "stability_score": stability_score,
        "vote_split": f"{pass_votes}/{fail_votes}",
        "result": primary_run["result"], # Primary result for structure
    }


def _compute_mode_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    LOGGER.info("Computing mode metrics for %d record(s)", len(records))
    labeled = [r for r in records if isinstance(r.get("expected_pass"), bool)]
    clean_rows = [r for r in labeled if r.get("error_class") != "provider_error"]
    error_rows = [r for r in labeled if r.get("error_class") == "provider_error"]
    cm = _confusion_from_rows(labeled)
    clean_cm = _confusion_from_rows(clean_rows)
    tp = cm["tp"]
    fp = cm["fp"]
    tn = cm["tn"]
    fn = cm["fn"]
    clean_tp = clean_cm["tp"]
    clean_fp = clean_cm["fp"]
    clean_tn = clean_cm["tn"]
    clean_fn = clean_cm["fn"]
    latency = [float(r["latency_ms"]) for r in records]
    stability = [float(r.get("stability_score", 1.0)) for r in records]

    reason_recall_values: List[float] = []
    reason_precision_values: List[float] = []
    over_flagging_count = 0
    for row in labeled:
        expected_reasons = set(row.get("expected_fail_reasons", []))
        predicted_reasons = set(row.get("predicted_reason_codes", []))
        if _branch(
            "compute_mode_metrics.has_expected_reasons",
            bool(expected_reasons),
            f"case_id={row.get('case_id')} has expected reasons",
            f"case_id={row.get('case_id')} has no expected reasons",
        ):
            reason_recall_values.append(
                len(expected_reasons.intersection(predicted_reasons))
                / len(expected_reasons)
            )
            if _branch(
                "compute_mode_metrics.over_flagging",
                len(predicted_reasons) > 2 * len(expected_reasons),
                f"case_id={row.get('case_id')} counted as over-flagging",
                f"case_id={row.get('case_id')} not over-flagging",
            ):
                over_flagging_count += 1
        if _branch(
            "compute_mode_metrics.has_predicted_reasons",
            bool(predicted_reasons),
            f"case_id={row.get('case_id')} has predicted reasons",
            f"case_id={row.get('case_id')} has no predicted reasons",
        ):
            if _branch(
                "compute_mode_metrics.predicted_and_expected_reasons",
                bool(expected_reasons),
                f"case_id={row.get('case_id')} precision computed against expected reasons",
                f"case_id={row.get('case_id')} precision forced to 0.0",
            ):
                reason_precision_values.append(
                    len(expected_reasons.intersection(predicted_reasons))
                    / len(predicted_reasons)
                )
            else:
                reason_precision_values.append(0.0)

    precision = _precision(tp, fp)
    recall = _recall(tp, fn)
    clean_precision = _precision(clean_tp, clean_fp)
    clean_recall = _recall(clean_tp, clean_fn)
    accuracy = None
    clean_accuracy = None
    if _branch(
        "compute_mode_metrics.has_labeled",
        bool(labeled),
        f"Computing accuracy with labeled_count={len(labeled)}",
        "No labeled rows; accuracy=None",
    ):
        accuracy = (tp + tn) / len(labeled)
    if _branch(
        "compute_mode_metrics.has_clean_rows",
        bool(clean_rows),
        f"Computing clean accuracy with clean_count={len(clean_rows)}",
        "No clean rows; clean_accuracy=None",
    ):
        clean_accuracy = (clean_tp + clean_tn) / len(clean_rows)
    reason_recall_macro = _safe_mean(reason_recall_values)
    reason_precision_macro = _safe_mean(reason_precision_values)
    reason_f1_macro = _f1(reason_precision_macro, reason_recall_macro)

    return {
        "num_cases": len(records),
        "num_labeled_cases": len(labeled),
        "confusion_matrix_fail_class": cm,
        "precision_fail": precision,
        "precision_fail_ci_95": _bootstrap_metric_ci(labeled, "precision_fail"),
        "recall_fail": recall,
        "recall_fail_ci_95": _bootstrap_metric_ci(labeled, "recall_fail"),
        "f1_fail": _f1(precision, recall),
        "f1_fail_ci_95": _bootstrap_metric_ci(labeled, "f1_fail"),
        "accuracy": accuracy,
        "accuracy_ci_95": _bootstrap_metric_ci(labeled, "accuracy"),
        "provider_error_count": len(error_rows),
        "clean_cases": len(clean_rows),
        "clean_confusion_matrix": clean_cm,
        "clean_accuracy": clean_accuracy,
        "clean_precision_fail": clean_precision,
        "clean_recall_fail": clean_recall,
        "clean_f1_fail": _f1(clean_precision, clean_recall),
        "reason_recall_macro": reason_recall_macro,
        "reason_precision_macro": reason_precision_macro,
        "reason_f1_macro": reason_f1_macro,
        "over_flagging_rate": (
            over_flagging_count / len(labeled) if labeled else None
        ),
        "latency_ms_avg": _safe_mean(latency),
        "latency_ms_median": _safe_median(latency),
        "stability_avg": _safe_mean(stability),
    }


def _compute_disagreements(raw: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    LOGGER.info("Computing disagreements across %d raw record(s)", len(raw))
    by_case: Dict[str, Dict[str, bool]] = defaultdict(dict)
    for row in raw:
        by_case[row["case_id"]][row["mode"]] = bool(row["predicted_pass"])

    pairs = [("deterministic", "llm"), ("deterministic", "hybrid"), ("llm", "hybrid")]
    disagreements: Dict[str, List[str]] = {}
    for left, right in pairs:
        key = f"{left}_vs_{right}"
        disagreements[key] = []
        for case_id, decisions in by_case.items():
            if _branch(
                "compute_disagreements.pair_disagree",
                left in decisions and right in decisions and decisions[left] != decisions[right],
                f"case_id={case_id} disagreement for {left} vs {right}",
                f"case_id={case_id} no disagreement for {left} vs {right}",
            ):
                disagreements[key].append(case_id)
    return disagreements


def _fmt_pct(value: Optional[float]) -> str:
    if _branch("fmt_pct.none_value", value is None, "Formatting None as '-'", "Formatting percent"):
        return "-"
    return f"{value * 100:.1f}%"


def _fmt_float(value: Optional[float]) -> str:
    if _branch("fmt_float.none_value", value is None, "Formatting None as '-'", "Formatting float"):
        return "-"
    return f"{value:.2f}"


def _build_summary_markdown(
    *,
    run_timestamp: str,
    cases_path: Path,
    modes: Sequence[str],
    metrics: Dict[str, Dict[str, Any]],
    disagreements: Dict[str, List[str]],
) -> str:
    LOGGER.info("Building summary markdown for modes=%s", ",".join(modes))
    lines: List[str] = []
    lines.append("# Spec Validation Evaluation Summary")
    lines.append("")
    lines.append(f"- Run timestamp (UTC): `{run_timestamp}`")
    lines.append(f"- Cases file: `{cases_path}`")
    lines.append(f"- Modes: `{', '.join(modes)}`")
    lines.append("")
    lines.append(
        "| Mode | Cases | Labeled | Accuracy | Precision (fail) | Recall (fail) | Stability | Reason Recall | Reason Prec | Over-flag % | Avg Latency ms | Median Latency ms |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for mode in modes:
        m = metrics[mode]
        lines.append(
            "| "
            + " | ".join(
                [
                    mode,
                    str(m["num_cases"]),
                    str(m["num_labeled_cases"]),
                    f"{_fmt_pct(m['accuracy'])} {_fmt_ci(m.get('accuracy_ci_95'))}",
                    f"{_fmt_pct(m['precision_fail'])} {_fmt_ci(m.get('precision_fail_ci_95'))}",
                    f"{_fmt_pct(m['recall_fail'])} {_fmt_ci(m.get('recall_fail_ci_95'))}",
                    _fmt_pct(m.get("stability_avg")),
                    _fmt_pct(m["reason_recall_macro"]),
                    _fmt_pct(m.get("reason_precision_macro")),
                    _fmt_pct(m.get("over_flagging_rate")),
                    _fmt_float(m["latency_ms_avg"]),
                    _fmt_float(m["latency_ms_median"]),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Clean Metrics (provider errors excluded)")
    lines.append("")
    lines.append(
        "| Mode | Provider Errors | Clean Cases | Clean Accuracy | Clean Precision (fail) | Clean Recall (fail) | Clean F1 (fail) |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for mode in modes:
        m = metrics[mode]
        lines.append(
            "| "
            + " | ".join(
                [
                    mode,
                    str(m.get("provider_error_count", 0)),
                    str(m.get("clean_cases", 0)),
                    _fmt_pct(m.get("clean_accuracy")),
                    _fmt_pct(m.get("clean_precision_fail")),
                    _fmt_pct(m.get("clean_recall_fail")),
                    _fmt_pct(m.get("clean_f1_fail")),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Disagreements")
    for pair, case_ids in disagreements.items():
        lines.append(f"- `{pair}`: {len(case_ids)} case(s)")
        if _branch(
            "build_summary_markdown.has_disagreement_sample",
            bool(case_ids),
            f"Adding disagreement sample for pair={pair}",
            f"No disagreement sample for pair={pair}",
        ):
            preview = ", ".join(case_ids[:20])
            lines.append(f"  - Sample: {preview}")

    return "\n".join(lines) + "\n"


def evaluate_cases(cases: List[Dict[str, Any]], modes: Sequence[str], consensus_runs: int) -> Dict[str, Any]:
    LOGGER.info("Evaluating %d case(s) across mode(s): %s", len(cases), ", ".join(modes))
    raw_rows: List[Dict[str, Any]] = []
    by_mode: Dict[str, List[Dict[str, Any]]] = {mode: [] for mode in modes}

    for case_idx, case in enumerate(cases, start=1):
        LOGGER.info("Evaluating case %d/%d case_id=%s", case_idx, len(cases), case.get("case_id"))
        for mode in modes:
            row = _run_case_mode(case, mode, consensus_runs)
            raw_rows.append(row)
            by_mode[mode].append(row)

    mode_metrics = {mode: _compute_mode_metrics(rows) for mode, rows in by_mode.items()}
    disagreements = _compute_disagreements(raw_rows)
    return {
        "raw_rows": raw_rows,
        "mode_metrics": mode_metrics,
        "disagreements": disagreements,
    }


def _limit_cases(
    cases: List[Dict[str, Any]],
    *,
    limit: int,
    stratify: bool,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Limit cases with optional stratified sampling by expected_pass label."""
    LOGGER.info(
        "Applying case limit: total=%d limit=%d stratify=%s seed=%d",
        len(cases),
        limit,
        stratify,
        seed,
    )
    if _branch(
        "limit_cases.no_limit_needed",
        (limit <= 0 or len(cases) <= limit),
        "Returning all cases without sampling",
        "Proceeding with limiting/sampling",
    ):
        return cases
    if _branch(
        "limit_cases.non_stratified",
        not stratify,
        f"Returning first {limit} cases (non-stratified)",
        "Using stratified sampling",
    ):
        return cases[:limit]

    rng = random.Random(seed)
    positives = [c for c in cases if c.get("expected_pass") is True]
    negatives = [c for c in cases if c.get("expected_pass") is False]
    unlabeled = [c for c in cases if c.get("expected_pass") is None]

    labeled_count = len(positives) + len(negatives)
    if _branch(
        "limit_cases.no_labeled_cases",
        labeled_count == 0,
        f"No labeled cases; fallback to first {limit}",
        "Labeled cases present; computing stratified targets",
    ):
        return cases[:limit]

    target_pos = round(limit * (len(positives) / labeled_count))
    target_neg = limit - target_pos
    target_pos = min(target_pos, len(positives))
    target_neg = min(target_neg, len(negatives))

    selected: List[Dict[str, Any]] = []
    selected.extend(rng.sample(positives, target_pos) if target_pos > 0 else [])
    selected.extend(rng.sample(negatives, target_neg) if target_neg > 0 else [])

    remaining = limit - len(selected)
    leftovers = [c for c in cases if c not in selected]
    if _branch(
        "limit_cases.fill_remaining",
        (remaining > 0 and bool(leftovers)),
        f"Need to fill remaining={remaining} from leftovers={len(leftovers)}",
        "No fill from leftovers needed",
    ):
        if _branch(
            "limit_cases.leftovers_fit",
            len(leftovers) <= remaining,
            "Taking all leftovers",
            "Sampling leftovers",
        ):
            selected.extend(leftovers)
        else:
            selected.extend(rng.sample(leftovers, remaining))

    rng.shuffle(selected)
    return selected


def _validate_min_positive_cases(
    cases: Sequence[Dict[str, Any]],
    *,
    min_positive_cases: int,
) -> None:
    LOGGER.info("Validating min positive cases: threshold=%d", min_positive_cases)
    if _branch(
        "validate_min_positive_cases.skip_check",
        min_positive_cases <= 0,
        "Threshold disabled; skipping check",
        "Threshold enabled; checking count",
    ):
        return
    positive_count = sum(1 for case in cases if case.get("expected_pass") is True)
    if _branch(
        "validate_min_positive_cases.too_few_positives",
        positive_count < min_positive_cases,
        f"Too few positives ({positive_count} < {min_positive_cases}); raising",
        f"Positive coverage ok ({positive_count} >= {min_positive_cases})",
    ):
        raise SystemExit(
            f"Expected at least {min_positive_cases} expected-pass cases, got {positive_count}."
        )


def parse_modes(raw_modes: str) -> List[str]:
    LOGGER.info("Parsing modes from input: %s", raw_modes)
    if _branch(
        "parse_modes.all",
        raw_modes == "all",
        "Using all valid modes",
        "Parsing explicit mode list",
    ):
        return list(VALID_MODES)
    modes = [m.strip() for m in raw_modes.split(",") if m.strip()]
    invalid = [m for m in modes if m not in VALID_MODES]
    if _branch(
        "parse_modes.has_invalid",
        bool(invalid),
        f"Invalid modes found: {invalid}",
        "No invalid modes found",
    ):
        raise ValueError(f"Invalid mode(s): {invalid}. Valid: {list(VALID_MODES)} or all")
    if _branch(
        "parse_modes.empty_modes",
        not modes,
        "No modes after parsing; raising",
        f"Using parsed modes: {modes}",
    ):
        raise ValueError("At least one mode is required")
    return modes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate spec validation quality across deterministic/llm/hybrid modes"
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("artifacts") / "validation_benchmark" / "cases.jsonl",
        help="Benchmark cases JSONL",
    )
    parser.add_argument(
        "--modes",
        type=str,
        default="all",
        help="Validation modes: all or comma-separated deterministic,llm,hybrid",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts") / "validation_eval",
        help="Output folder for evaluation artifacts",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of cases to evaluate (0 means all)",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include cases where enabled=false",
    )
    parser.add_argument(
        "--stratify",
        action="store_true",
        help="When used with --limit, sample cases with class balance by expected_pass.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used for stratified sampling/bootstrap reproducibility.",
    )
    parser.add_argument(
        "--min-positive-cases",
        type=int,
        default=0,
        help="Fail run if selected cases have fewer than this many expected_pass=True labels.",
    )
    parser.add_argument(
        "--consensus-runs",
        type=int,
        default=1,
        help="Number of times to run LLM/Hybrid modes per case to determine consensus (default: 1)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity. Use DEBUG for branch-level trace logs.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.setLevel(getattr(logging, args.log_level))
    LOGGER.info("Starting eval_spec_validation")
    LOGGER.info("CLI args: %s", vars(args))

    modes = parse_modes(args.modes)
    cases = _read_cases(args.cases, include_disabled=args.include_disabled)
    cases = _limit_cases(
        cases,
        limit=args.limit,
        stratify=args.stratify,
        seed=args.seed,
    )
    _validate_min_positive_cases(cases, min_positive_cases=args.min_positive_cases)
    if _branch(
        "main.no_cases",
        not cases,
        "No cases found after filtering/limiting; exiting",
        f"Proceeding with {len(cases)} case(s)",
    ):
        raise SystemExit("No benchmark cases found. Build or provide cases first.")

    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    evaluated = evaluate_cases(cases, modes, args.consensus_runs)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"raw_{run_timestamp}.jsonl"
    results_path = output_dir / f"results_{run_timestamp}.json"
    summary_path = output_dir / f"summary_{run_timestamp}.md"

    _write_jsonl(raw_path, evaluated["raw_rows"])
    results_payload = {
        "run_timestamp_utc": run_timestamp,
        "cases_file": str(args.cases),
        "modes": modes,
        "num_cases": len(cases),
        "consensus_runs": args.consensus_runs,
        "mode_metrics": evaluated["mode_metrics"],
        "disagreements": evaluated["disagreements"],
        "raw_path": str(raw_path),
    }
    results_path.write_text(
        json.dumps(results_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        _build_summary_markdown(
            run_timestamp=run_timestamp,
            cases_path=args.cases,
            modes=modes,
            metrics=evaluated["mode_metrics"],
            disagreements=evaluated["disagreements"],
        ),
        encoding="utf-8",
    )
    LOGGER.info("Artifacts written: raw=%s results=%s summary=%s", raw_path, results_path, summary_path)

    for mode in modes:
        cm = evaluated["mode_metrics"][mode]["confusion_matrix_fail_class"]
        if _branch(
            "main.no_expected_pass_coverage_warning",
            cm.get("tn") == 0 and cm.get("fp") == 0,
            f"Mode {mode} has no expected-pass coverage; emitting warning",
            f"Mode {mode} has expected-pass coverage",
        ):
            print(
                (
                    f"WARNING [{mode}]: No expected-pass coverage detected "
                    "(tn=0 and fp=0). Consider --stratify or --min-positive-cases."
                ),
                file=sys.stderr,
            )

    print(f"Evaluated {len(cases)} case(s) across mode(s): {', '.join(modes)}")
    print(f"Raw results: {raw_path}")
    print(f"Metrics JSON: {results_path}")
    print(f"Summary MD: {summary_path}")
    LOGGER.info("Evaluation completed")


if __name__ == "__main__":
    main()
