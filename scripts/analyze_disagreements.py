"""Script for analyze disagreements."""

import collections
import json
from pathlib import Path

from utils.cli_output import emit


def analyze_disagreements(raw_path: str | Path) -> None:
    """Return analyze disagreements."""
    with open(raw_path) as f:  # noqa: PTH123
        rows = [json.loads(line) for line in f if line.strip()]

    # Group by case_id
    cases = collections.defaultdict(dict)
    for row in rows:
        cases[row["case_id"]][row["mode"]] = row

    disagreements = []
    for case_id, modes in cases.items():
        det = modes.get("deterministic", {}).get("predicted_pass")
        llm = modes.get("llm", {}).get("predicted_pass")
        hyb = modes.get("hybrid", {}).get("predicted_pass")

        if len({det, llm, hyb}) > 1:
            disagreements.append(
                {
                    "case_id": case_id,
                    "story_title": modes["deterministic"]
                    .get("result", {})
                    .get("story", {})
                    .get("title", "Unknown"),  # access might be different
                    "deterministic": det,
                    "llm": llm,
                    "hybrid": hyb,
                    "det_reasons": modes.get("deterministic", {}).get(
                        "predicted_reason_codes", []
                    ),
                    "llm_reasons": modes.get("llm", {}).get(
                        "predicted_reason_codes", []
                    ),
                    "hyb_reasons": modes.get("hybrid", {}).get(
                        "predicted_reason_codes", []
                    ),
                }
            )

    emit(f"Found {len(disagreements)} disagreements:")
    for d in disagreements:
        emit(f"\nCase: {d['case_id']}")
        emit(f"  Det: {d['deterministic']} {d['det_reasons']}")
        emit(f"  LLM: {d['llm']} {d['llm_reasons']}")
        emit(f"  Hyb: {d['hybrid']} {d['hyb_reasons']}")


if __name__ == "__main__":
    analyze_disagreements("artifacts/validation_eval/raw_20260216_210438.jsonl")
