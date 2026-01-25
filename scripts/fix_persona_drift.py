# scripts/fix_persona_drift.py
"""
Automated persona correction for existing user stories.

This script identifies stories with incorrect/generic personas and replaces them
with domain-specific personas. Safe to run with dry_run=True for preview.

Usage:
    # Preview changes
    python scripts/fix_persona_drift.py --product-id 1 --dry-run

    # Apply changes
    python scripts/fix_persona_drift.py --product-id 1

    # Generate review report
    python scripts/fix_persona_drift.py --product-id 1 --report-only
"""

import argparse
import csv
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select
from agile_sqlmodel import UserStory, Product, Feature, engine
from orchestrator_agent.agent_tools.story_pipeline.persona_checker import (
    extract_persona_from_story,
    validate_persona,
    auto_correct_persona,
    detect_generic_personas,
    suggest_persona_replacement,
)


# --- Configuration ---

# Persona substitution rules for automated fixes
PERSONA_FIXES = {
    "data annotator": "automation engineer",
    "software engineer": "automation engineer",
    "frontend developer": "automation engineer",
    "backend developer": "automation engineer",
    "developer": "automation engineer",
    "qa engineer": "engineering QA reviewer",
    "data scientist": "automation engineer",  # Unless ML context
    "user": "automation engineer",  # Default - may need manual review
}


def analyze_product_personas(product_id: int) -> dict:
    """
    Analyze persona distribution in a product's stories.

    Args:
        product_id: Product ID to analyze

    Returns:
        Dict with persona statistics
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()

        persona_counts = {}
        generic_count = 0
        no_persona_count = 0

        for story in stories:
            persona = extract_persona_from_story(story.description)

            if not persona:
                no_persona_count += 1
            else:
                persona_lower = persona.lower().strip()
                persona_counts[persona_lower] = persona_counts.get(persona_lower, 0) + 1

                if detect_generic_personas(story.description):
                    generic_count += 1

        return {
            "product_name": product.product_name,
            "total_stories": len(stories),
            "persona_distribution": persona_counts,
            "generic_persona_count": generic_count,
            "no_persona_count": no_persona_count,
        }


def fix_story_personas(
    product_id: int,
    target_persona: str = "automation engineer",
    dry_run: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Fix personas in all stories for a product.

    Args:
        product_id: Product ID to fix
        target_persona: Default persona to use for generic replacements
        dry_run: If True, preview changes without saving
        verbose: Print detailed output

    Returns:
        Dict with fix statistics
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()

        fixed_count = 0
        skipped_count = 0
        changes = []

        for story in stories:
            # Extract current persona
            current_persona = extract_persona_from_story(story.description)

            if not current_persona:
                skipped_count += 1
                if verbose:
                    print(
                        f"⚠️  Story {story.story_id}: No persona found - SKIPPED (manual review needed)"
                    )
                continue

            # Check if persona needs fixing
            persona_lower = current_persona.lower().strip()

            # Determine correct persona
            if persona_lower in PERSONA_FIXES:
                # Use mapping for known generic personas
                new_persona = PERSONA_FIXES[persona_lower]

                # Check for ML context override
                feature_title = story.feature.feature_title if story.feature else ""
                if "train" in feature_title.lower() or "model" in feature_title.lower():
                    new_persona = "ML engineer"

            elif persona_lower == target_persona.lower():
                # Already correct
                continue

            else:
                # Unknown persona - skip for manual review
                skipped_count += 1
                if verbose:
                    print(
                        f"⚠️  Story {story.story_id}: Unknown persona '{current_persona}' - SKIPPED (manual review needed)"
                    )
                continue

            # Apply correction
            old_desc = story.description
            story_dict = {"description": old_desc}
            corrected_dict = auto_correct_persona(story_dict, new_persona)
            new_desc = corrected_dict["description"]

            if old_desc != new_desc:
                change_record = {
                    "story_id": story.story_id,
                    "feature": story.feature.feature_title if story.feature else "N/A",
                    "old_persona": current_persona,
                    "new_persona": new_persona,
                    "old_description": old_desc[:80] + "...",
                    "new_description": new_desc[:80] + "...",
                }
                changes.append(change_record)

                if verbose:
                    print(
                        f"✅ Story {story.story_id}: '{current_persona}' → '{new_persona}'"
                    )

                if not dry_run:
                    story.description = new_desc
                    session.add(story)

                fixed_count += 1

        if not dry_run and fixed_count > 0:
            session.commit()
            if verbose:
                print(f"\n💾 Committed {fixed_count} changes to database")

        stats = {
            "total_stories": len(stories),
            "fixed_count": fixed_count,
            "skipped_count": skipped_count,
            "changes": changes,
        }

        return stats


def generate_review_report(product_id: int, output_file: str = "persona_review.csv"):
    """
    Generate CSV report for manual persona review.

    Args:
        product_id: Product ID to report on
        output_file: Output CSV filename
    """
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Story ID",
                    "Feature",
                    "Current Persona",
                    "Is Generic?",
                    "Suggested Fix",
                    "Description",
                    "Acceptance Criteria",
                    "Review Status",
                ]
            )

            for story in stories:
                current_persona = extract_persona_from_story(story.description)
                is_generic = detect_generic_personas(story.description)

                # Suggest fix
                if current_persona and current_persona.lower() in PERSONA_FIXES:
                    suggested = PERSONA_FIXES[current_persona.lower()]
                elif is_generic:
                    feature_title = story.feature.feature_title if story.feature else ""
                    suggested = suggest_persona_replacement(
                        current_persona or "", feature_title
                    )
                else:
                    suggested = "OK" if current_persona else "MISSING"

                writer.writerow(
                    [
                        story.story_id,
                        story.feature.feature_title if story.feature else "N/A",
                        current_persona or "MISSING",
                        "YES" if is_generic else "NO",
                        suggested or "MANUAL_REVIEW",
                        story.description[:100],
                        story.acceptance_criteria[:100] if story.acceptance_criteria else "",
                        "PENDING",
                    ]
                )

    print(f"📊 Review report saved to {output_file}")
    print(f"   Open in Excel/Sheets for manual review")


def main():
    parser = argparse.ArgumentParser(
        description="Fix persona drift in user stories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes
  python scripts/fix_persona_drift.py --product-id 1 --dry-run

  # Apply fixes
  python scripts/fix_persona_drift.py --product-id 1

  # Use custom default persona
  python scripts/fix_persona_drift.py --product-id 1 --persona "engineering QA reviewer"

  # Generate manual review report
  python scripts/fix_persona_drift.py --product-id 1 --report-only
        """,
    )

    parser.add_argument(
        "--product-id", type=int, required=True, help="Product ID to process"
    )
    parser.add_argument(
        "--persona",
        type=str,
        default="automation engineer",
        help="Default persona for replacements (default: automation engineer)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without saving"
    )
    parser.add_argument(
        "--report-only", action="store_true", help="Generate CSV report only (no fixes)"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress detailed output"
    )

    args = parser.parse_args()

    try:
        if args.report_only:
            print(f"Generating persona review report for product {args.product_id}...")
            generate_review_report(args.product_id)

        else:
            # Analyze first
            print(f"Analyzing product {args.product_id}...\n")
            analysis = analyze_product_personas(args.product_id)

            print(f"Product: {analysis['product_name']}")
            print(f"Total Stories: {analysis['total_stories']}")
            print(f"Generic Personas: {analysis['generic_persona_count']}")
            print(f"Missing Personas: {analysis['no_persona_count']}")
            print("\nPersona Distribution:")
            for persona, count in sorted(
                analysis["persona_distribution"].items(), key=lambda x: x[1], reverse=True
            ):
                marker = "⚠️ " if persona in PERSONA_FIXES else "✅ "
                print(f"  {marker}{persona}: {count}")

            print(
                f"\n{'=' * 60}\n{'PREVIEW MODE - No changes will be saved' if args.dry_run else 'APPLYING FIXES'}\n{'=' * 60}\n"
            )

            # Fix personas
            stats = fix_story_personas(
                args.product_id,
                target_persona=args.persona,
                dry_run=args.dry_run,
                verbose=not args.quiet,
            )

            # Summary
            print(f"\n{'=' * 60}")
            print("SUMMARY")
            print(f"{'=' * 60}")
            print(f"Total Stories: {stats['total_stories']}")
            print(f"Fixed: {stats['fixed_count']}")
            print(f"Skipped (manual review): {stats['skipped_count']}")

            if args.dry_run and stats["fixed_count"] > 0:
                print("\n💡 Run without --dry-run to apply these changes")

            if stats["skipped_count"] > 0:
                print(
                    f"\n⚠️  {stats['skipped_count']} stories require manual review"
                )
                print("   Run with --report-only to generate a review CSV")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
