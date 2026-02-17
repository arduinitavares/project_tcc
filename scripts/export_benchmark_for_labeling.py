#!/usr/bin/env python3
"""Export benchmark cases to a human-labeling file with story/spec context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from agile_sqlmodel import (  # pylint: disable=wrong-import-position
    CompiledSpecAuthority,
    UserStory,
    get_engine,
)
from tools.spec_tools import _load_compiled_artifact  # pylint: disable=wrong-import-position


def _read_cases(path: Path, include_disabled: bool = False) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if not include_disabled and case.get("enabled", True) is False:
                continue
            if not isinstance(case.get("story_id"), int) or not isinstance(
                case.get("spec_version_id"), int
            ):
                raise ValueError(
                    f"Invalid case on line {idx}: story_id/spec_version_id must be int"
                )
            case.setdefault("case_id", f"case-{idx}")
            rows.append(case)
    return rows


def _summarize_authority(compiled: Optional[CompiledSpecAuthority]) -> str:
    """Render compact summary of compiled authority for reviewer context."""
    if not compiled:
        return "NO_COMPILED_AUTHORITY"
    artifact = _load_compiled_artifact(compiled)
    if not artifact:
        return "INVALID_COMPILED_AUTHORITY_ARTIFACT"

    invariants = [f"{inv.id}:{inv.type}" for inv in artifact.invariants[:20]]
    scope = artifact.scope_themes[:10]
    payload = {
        "scope_themes": scope,
        "invariants": invariants,
        "gaps": artifact.gaps[:10],
    }
    return json.dumps(payload, ensure_ascii=True)


def build_labeling_rows(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build reviewer rows by joining story/spec authority context."""
    rows: List[Dict[str, Any]] = []
    with Session(get_engine()) as session:
        for case in cases:
            story = session.get(UserStory, case["story_id"])
            compiled = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == case["spec_version_id"]
                )
            ).first()

            title = (story.title if story else "") or ""
            description = (story.story_description if story else "") or ""
            acceptance_criteria = (story.acceptance_criteria if story else "") or ""

            rows.append(
                {
                    "case_id": case["case_id"],
                    "story_id": case["story_id"],
                    "spec_version_id": case["spec_version_id"],
                    "story_title": title,
                    "story_description": description,
                    "acceptance_criteria": acceptance_criteria,
                    "spec_authority_summary": _summarize_authority(compiled),
                    "rater_pass": "",
                    "rater_fail_reasons": "",
                    "rater_confidence": "",
                    "rater_notes": "",
                    "rater_id": "",
                }
            )
    return rows


def _fieldnames() -> List[str]:
    return [
        "case_id",
        "story_id",
        "spec_version_id",
        "story_title",
        "story_description",
        "acceptance_criteria",
        "spec_authority_summary",
        "rater_pass",
        "rater_fail_reasons",
        "rater_confidence",
        "rater_notes",
        "rater_id",
    ]


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Write rows to JSONL for manual labeling and diff-friendly review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            output = {key: row.get(key, "") for key in _fieldnames()}
            handle.write(json.dumps(output, ensure_ascii=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export benchmark cases to a reviewer-friendly JSONL"
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("artifacts") / "validation_benchmark" / "cases.jsonl",
        help="Input benchmark JSONL file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts") / "validation_benchmark" / "cases_for_labeling.jsonl",
        help="Output JSONL path for human labeling",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include cases with enabled=false",
    )
    args = parser.parse_args()

    cases = _read_cases(args.cases, include_disabled=args.include_disabled)
    rows = build_labeling_rows(cases)
    write_jsonl(args.output, rows)
    print(f"Exported {len(rows)} case(s) to: {args.output}")
    print("Fill rater_* columns, then import using scripts/import_human_labels.py")


if __name__ == "__main__":
    main()
