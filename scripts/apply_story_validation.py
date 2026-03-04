#!/usr/bin/env python3
"""
Applies validation to all stories against the approved spec authority.
Persists results to the database using the official tool.
"""
import sys
import os
import re
from pathlib import Path
from sqlmodel import Session, select

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from agile_sqlmodel import Product, UserStory, SpecRegistry, CompiledSpecAuthority, get_engine
from tools.spec_tools import validate_story_with_spec_authority

engine = get_engine()

def _effective_mode(explicit_mode: str | None) -> str:
    if explicit_mode:
        return explicit_mode
    return os.getenv("SPEC_VALIDATION_DEFAULT_MODE", "deterministic").strip().lower() or "deterministic"


def _load_invariant_map(spec_version_id: int) -> dict[str, dict]:
    with Session(engine) as session:
        auth = session.exec(
            select(CompiledSpecAuthority).where(CompiledSpecAuthority.spec_version_id == spec_version_id)
        ).first()
    if not auth or not auth.compiled_artifact_json:
        return {}
    try:
        import json

        artifact = json.loads(auth.compiled_artifact_json)
        invariants = artifact.get("invariants", []) if isinstance(artifact, dict) else []
        return {
            inv.get("id"): inv
            for inv in invariants
            if isinstance(inv, dict) and isinstance(inv.get("id"), str)
        }
    except Exception:
        return {}


def _extract_invariant_ids(*texts: str) -> list[str]:
    ids: list[str] = []
    for txt in texts:
        for match in re.findall(r"INV-[a-f0-9]{16}", txt or "", flags=re.IGNORECASE):
            ids.append("INV-" + match[4:].lower())
    # stable de-duplication
    seen = set()
    ordered: list[str] = []
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        ordered.append(i)
    return ordered


def apply_validation(product_id: int, mode: str | None = None):
    active_mode = _effective_mode(mode)
    print(f"Applying validation to Product {product_id}...")
    print(f"Validation mode: {active_mode}")
    with Session(engine) as session:
        # Get approved spec
        spec = session.exec(select(SpecRegistry).where(
            SpecRegistry.product_id == product_id,
            SpecRegistry.status == "approved"
        ).order_by(SpecRegistry.spec_version_id.desc())).first()
        
        if not spec:
            print("No approved spec found.")
            return

        spec_id = spec.spec_version_id
        print(f"Using Spec Version {spec_id}")
        invariant_map = _load_invariant_map(spec_id)
        
        # Validate only canonical refined stories.
        stories = session.exec(
            select(UserStory)
            .where(UserStory.product_id == product_id)
            .where(UserStory.is_refined == True)  # noqa: E712
            .where(UserStory.is_superseded == False)  # noqa: E712
            .order_by(UserStory.story_id.asc())
        ).all()
        ids = [s.story_id for s in stories]

    if not ids:
        print("No refined stories found for this product. Nothing to validate.")
        return

    # Validate
    passed_count = 0
    for sid in ids:
        print(f"Validating {sid}...", end=" ")
        try:
            # Tool handles commit
            res = validate_story_with_spec_authority(
                {"story_id": sid, "spec_version_id": spec_id, "mode": active_mode}
            )
            if res.get("passed"):
                print("PASS")
                passed_count += 1
            else:
                print("FAIL")
                failures = res.get("failures", []) or []
                alignment_failures = res.get("alignment_failures", []) or []
                printed_any_reason = False

                if failures:
                    printed_any_reason = True
                    for failure in failures[:3]:
                        rule = failure.get("rule", "UNKNOWN_RULE")
                        actual = failure.get("actual", "")
                        print(f"  - {rule}: {actual}")
                        inv_ids = _extract_invariant_ids(actual, failure.get("message", ""))
                        for inv_id in inv_ids:
                            inv = invariant_map.get(inv_id)
                            if not inv:
                                continue
                            inv_type = inv.get("type", "UNKNOWN")
                            params = inv.get("parameters", {}) if isinstance(inv.get("parameters"), dict) else {}
                            field_name = params.get("field_name")
                            capability = params.get("capability")
                            if field_name:
                                print(f"    -> {inv_id} [{inv_type}] field_name={field_name}")
                            elif capability:
                                print(f"    -> {inv_id} [{inv_type}] capability={capability}")
                            else:
                                print(f"    -> {inv_id} [{inv_type}]")
                    if len(failures) > 3:
                        print(f"  - ... and {len(failures) - 3} more failure(s)")

                if alignment_failures:
                    printed_any_reason = True
                    for finding in alignment_failures[:3]:
                        code = finding.get("code", "ALIGNMENT_FAILURE")
                        message = finding.get("message", "")
                        invariant = finding.get("invariant")
                        if invariant:
                            print(f"  - {code} ({invariant}): {message}")
                        else:
                            print(f"  - {code}: {message}")
                    if len(alignment_failures) > 3:
                        print(
                            f"  - ... and {len(alignment_failures) - 3} more alignment failure(s)"
                        )

                if not printed_any_reason:
                    print(f"  - {res.get('message', 'Validation failed without details')}")
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"Done. Passed: {passed_count}/{len(ids)}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Apply spec-authority validation to all stories for a product."
    )
    parser.add_argument(
        "product_id",
        nargs="?",
        type=int,
        default=None,
        help="Product ID to validate. Defaults to the most recently created product.",
    )
    parser.add_argument(
        "--mode",
        choices=["deterministic", "llm", "hybrid"],
        default=None,
        help=(
            "Validation mode override. If omitted, uses "
            "SPEC_VALIDATION_DEFAULT_MODE from environment (fallback: deterministic)."
        ),
    )
    args = parser.parse_args()

    if args.product_id is None:
        with Session(engine) as _s:
            latest = _s.exec(
                select(Product)
                .order_by(Product.product_id.desc())
            ).first()
        if not latest:
            print("No products found in DB.")
            sys.exit(1)
        pid = latest.product_id
        print(f"(No product_id given — using latest: {pid} '{latest.name}')")
    else:
        pid = args.product_id

    apply_validation(pid, mode=args.mode)
