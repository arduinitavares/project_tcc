#!/usr/bin/env python3
"""Temporary debug script to investigate validation failures for product 8."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select
from agile_sqlmodel import UserStory, SpecRegistry, CompiledSpecAuthority, get_engine
from tools.spec_tools import validate_story_with_spec_authority, _load_compiled_artifact

engine = get_engine()

with Session(engine) as s:
    # Check spec version 9
    spec = s.get(SpecRegistry, 9)
    if spec:
        print(f"Spec 9: product_id={spec.product_id}, status={spec.status}")
    else:
        print("Spec 9: NOT FOUND")

    # Check authority for spec 9
    auth = s.exec(
        select(CompiledSpecAuthority).where(CompiledSpecAuthority.spec_version_id == 9)
    ).first()
    if auth:
        print(f"Authority for spec 9: authority_id={auth.authority_id}")
        print(f"  compiled_artifact_json present: {bool(auth.compiled_artifact_json)}")
        artifact = _load_compiled_artifact(auth)
        if artifact:
            print(f"  scope_themes: {artifact.scope_themes}")
            print(f"  invariants count: {len(artifact.invariants)}")
            for inv in artifact.invariants:
                print(f"    {inv.id}: {inv.type}")
        else:
            print("  Could not load artifact")
    else:
        print("Authority for spec 9: NOT FOUND")

    # Check stories
    stories = s.exec(select(UserStory).where(UserStory.product_id == 8)).all()
    print(f"\nStories for product 8: {len(stories)}")

    # Validate first story with verbose output
    if stories:
        st = stories[0]
        print(f"\n--- Sample Story {st.story_id} ---")
        print(f"  title: {st.title}")
        print(f"  product_id: {st.product_id}")
        has_ac = bool(st.acceptance_criteria and st.acceptance_criteria.strip())
        print(f"  acceptance_criteria present: {has_ac}")
        if st.acceptance_criteria:
            print(f"  acceptance_criteria (first 200): {st.acceptance_criteria[:200]}")
        desc = st.story_description or ""
        print(f"  description (first 200): {desc[:200]}")
        title_lower = (st.title or "").lower()
        desc_lower = desc.lower()
        has_persona = (
            "as a " in title_lower
            or "as a " in desc_lower
            or "as an " in title_lower
            or "as an " in desc_lower
        )
        print(f"  has persona format: {has_persona}")

        # Run actual validation
        print("\n--- Validation Result ---")
        res = validate_story_with_spec_authority(
            {"story_id": st.story_id, "spec_version_id": 9}
        )
        print(json.dumps(res, indent=2, default=str))
