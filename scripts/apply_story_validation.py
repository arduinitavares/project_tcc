#!/usr/bin/env python3
"""
Applies validation to all stories against the approved spec authority.
Persists results to the database using the official tool.
"""
import sys
from pathlib import Path
from sqlmodel import Session, select

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from agile_sqlmodel import Product, UserStory, SpecRegistry, get_engine
from tools.spec_tools import validate_story_with_spec_authority

engine = get_engine()

def apply_validation(product_id: int):
    print(f"Applying validation to Product {product_id}...")
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
        
        # Get stories
        stories = session.exec(select(UserStory).where(UserStory.product_id == product_id)).all()
        ids = [s.story_id for s in stories]

    # Validate
    passed_count = 0
    for sid in ids:
        print(f"Validating {sid}...", end=" ")
        try:
            # Tool handles commit
            res = validate_story_with_spec_authority({"story_id": sid, "spec_version_id": spec_id})
            if res.get("passed"):
                print("PASS")
                passed_count += 1
            else:
                print("FAIL")
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

    apply_validation(pid)
