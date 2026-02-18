#!/usr/bin/env python3
"""One-time reconciliation for mixed backlog/refinement rows."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from sqlmodel import Session, select

from agile_sqlmodel import UserStory, get_engine
from db.migrations import migrate_performance_indexes, migrate_user_story_refinement_linkage
from orchestrator_agent.agent_tools.story_linkage import normalize_requirement_key


@dataclass
class ReconcileSummary:
    product_id: int
    migrated_actions: List[str]
    canonical_story_ids: List[int]
    superseded_story_ids: List[int]
    placeholder_story_ids: List[int]
    unresolved_story_ids: List[int]

    def as_dict(self) -> Dict[str, object]:
        return {
            "product_id": self.product_id,
            "migrated_actions": self.migrated_actions,
            "canonical_story_ids": self.canonical_story_ids,
            "superseded_story_ids": self.superseded_story_ids,
            "placeholder_story_ids": self.placeholder_story_ids,
            "unresolved_story_ids": self.unresolved_story_ids,
            "canonical_count": len(self.canonical_story_ids),
            "superseded_count": len(self.superseded_story_ids),
            "placeholder_count": len(self.placeholder_story_ids),
            "unresolved_count": len(self.unresolved_story_ids),
        }


def _story_fingerprint(story: UserStory) -> Tuple[str, str, str]:
    return (
        normalize_requirement_key(story.title or ""),
        normalize_requirement_key(story.story_description or ""),
        normalize_requirement_key(story.acceptance_criteria or ""),
    )


def reconcile_product(product_id: int) -> ReconcileSummary:
    engine = get_engine()
    actions: List[str] = []
    actions.extend(migrate_user_story_refinement_linkage(engine))
    actions.extend(migrate_performance_indexes(engine))

    canonical_ids: List[int] = []
    superseded_ids: List[int] = []
    placeholder_ids: List[int] = []
    unresolved_ids: List[int] = []

    with Session(engine) as session:
        stories = session.exec(
            select(UserStory)
            .where(UserStory.product_id == product_id)
            .where(UserStory.is_superseded == False)  # noqa: E712
            .order_by(UserStory.story_id.asc())
        ).all()

        # Backfill linkage defaults for legacy rows where possible.
        for idx, story in enumerate(stories, start=1):
            if not story.source_requirement:
                story.source_requirement = normalize_requirement_key(story.title or "")
            if story.refinement_slot is None:
                story.refinement_slot = idx
            has_ac = bool((story.acceptance_criteria or "").strip())
            if story.story_origin is None:
                story.story_origin = "refined" if has_ac else "backlog_seed"
            if has_ac and not story.is_refined:
                story.is_refined = True
            if not has_ac and story.is_refined is None:
                story.is_refined = False
            session.add(story)

        # Deduplicate refined rows by strict fingerprint, keep earliest story_id canonical.
        refreshed = session.exec(
            select(UserStory)
            .where(UserStory.product_id == product_id)
            .where(UserStory.is_superseded == False)  # noqa: E712
            .order_by(UserStory.story_id.asc())
        ).all()

        by_fp: Dict[Tuple[str, str, str], List[UserStory]] = {}
        for story in refreshed:
            fp = _story_fingerprint(story)
            by_fp.setdefault(fp, []).append(story)

        for fp, group in by_fp.items():
            if not fp[2]:  # empty AC -> placeholder style
                for st in group:
                    placeholder_ids.append(int(st.story_id))
                continue

            canonical = group[0]
            canonical_ids.append(int(canonical.story_id))
            for duplicate in group[1:]:
                duplicate.is_superseded = True
                duplicate.superseded_by_story_id = canonical.story_id
                session.add(duplicate)
                superseded_ids.append(int(duplicate.story_id))

        # Legacy placeholders remain unresolved for manual review if no direct mapping.
        for st in refreshed:
            if not (st.acceptance_criteria or "").strip() and not st.is_superseded:
                unresolved_ids.append(int(st.story_id))

        session.commit()

    return ReconcileSummary(
        product_id=product_id,
        migrated_actions=actions,
        canonical_story_ids=sorted(set(canonical_ids)),
        superseded_story_ids=sorted(set(superseded_ids)),
        placeholder_story_ids=sorted(set(placeholder_ids)),
        unresolved_story_ids=sorted(set(unresolved_ids)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile mixed backlog/refinement stories.")
    parser.add_argument("--product-id", type=int, required=True, help="Product ID to reconcile.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path (default artifacts/query_results/reconcile_product_<id>.json)",
    )
    args = parser.parse_args()

    summary = reconcile_product(args.product_id)

    output = args.output or Path("artifacts/query_results") / f"reconcile_product_{args.product_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(summary.as_dict(), indent=2, ensure_ascii=False))
    print(f"Wrote reconciliation report: {output}")


if __name__ == "__main__":
    main()
