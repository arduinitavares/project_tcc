#!/usr/bin/env python3
"""Dry-run script to validate stories against spec authority without persisting changes."""  # noqa: E501

import argparse
import json
from typing import Any

from sqlmodel import Session, col, create_engine, select

from utils.cli_output import emit
from utils.runtime_config import DatabaseTarget, resolve_database_target


def resolve_db_target(explicit_db: str | None = None) -> DatabaseTarget:
    """Resolve the business DB target for dry-run validation."""
    return resolve_database_target(explicit_db, env_name="AGILEFORGE_DB_URL")


def _load_invariants(compiled_artifact_json: str | None) -> list[dict[str, Any]] | None:
    if not compiled_artifact_json:
        emit("ERROR: Compiled authority artifact is empty.")
        return None

    authority = json.loads(compiled_artifact_json)
    invariants = authority.get("invariants", [])
    return [inv for inv in invariants if isinstance(inv, dict)]


def dry_run_validation(product_id: int, db: str | None = None) -> None:  # noqa: C901, PLR0912
    """Return dry run validation."""
    from agile_sqlmodel import (  # noqa: PLC0415
        CompiledSpecAuthority,
        SpecRegistry,
        UserStory,
    )

    db_target = resolve_db_target(db)
    if db_target.sqlite_path is None or not db_target.sqlite_path.exists():
        msg = f"Database file not found: {db_target.sqlite_connect_target}"
        raise FileNotFoundError(
            msg
        )
    engine = create_engine(
        db_target.sqlite_url,
        connect_args={"check_same_thread": False},
    )

    emit(f"Connecting to DB: {db_target.sqlite_connect_target}")

    with Session(engine) as session:
        # 1. Get the APPROVED spec version for this product
        statement = (
            select(SpecRegistry)
            .where(
                SpecRegistry.product_id == product_id, SpecRegistry.status == "approved"
            )
            .order_by(col(SpecRegistry.spec_version_id).desc())
        )

        spec = session.exec(statement).first()

        if not spec:
            emit(f"ERROR: No approved spec found for product {product_id}")
            return

        emit(f"Using Spec Version {spec.spec_version_id} (ID: {spec.spec_version_id})")

        # 2. Get all stories for product
        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()

        emit(f"Found {len(stories)} stories to validate.")
        emit("-" * 60)

        passed_count = 0
        failed_count = 0

        # 3. Simulate validation for each
        # CAUTION: validating modifies the DB session, so we must NOT commit.
        # tools.spec_tools creates a NEW session. Use caution.
        # Actually `validate_story_with_spec_authority` manages its own session/commit.
        # To make this a DRY RUN, we should ideally invoke the logic without the commit.
        # But since the tool is hardcoded to commit, we can't easily suppress it
        # unless we monkeypatch Session.commit or reimplement the check.

        # PLAN B: Re-implement the check logic here to avoid side effects
        # Fetch compiled authority content
        compiled = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == spec.spec_version_id
            )
        ).first()

        if not compiled:
            emit("ERROR: No compiled authority found for this spec version.")
            return

        invariants = _load_invariants(compiled.compiled_artifact_json)
        if invariants is None:
            return

        emit(f"Loaded {len(invariants)} invariants from authority.")

        for story in stories:
            # Basic validation logic (simplified mirror of spec_tools)
            story_failures = []

            # Check 1: Required fields
            if not story.title:
                story_failures.append("Missing title")
            if not story.acceptance_criteria:
                story_failures.append("Missing acceptance_criteria")

            # Check 2: Invariants (simplified check)
            # Just checking forbidden terms as a sample
            for inv in invariants:
                if inv["type"] == "FORBIDDEN_CAPABILITY":
                    term = inv["parameters"].get("capability", "")
                    if term and term in (story.story_description or ""):
                        story_failures.append(f"Forbidden term found: {term}")

            # Result
            if not story_failures:
                status = "PASS"
                passed_count += 1
            else:
                status = "FAIL"
                failed_count += 1

            emit(f"Story {story.story_id}: {status}")
            emit(f"  Title: {story.title}")
            if status == "FAIL":
                emit(f"  Desc: {(story.story_description or '')[:100]}...")

            if story_failures:
                for f in story_failures:
                    emit(f"  - {f}")

        emit("-" * 60)
        emit(f"Validation Summary: {passed_count} PASSED, {failed_count} FAILED")
        emit(
            "NOTE: This dry run only checked basic fields and forbidden terms (simplified)."  # noqa: E501
        )
        emit("Real validation would be stricter but this confirms data shape.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Dry-run story validation against compiled spec authority.",
    )
    parser.add_argument("product_id", type=int, help="Product ID to inspect.")
    parser.add_argument(
        "--db",
        help="Optional SQLite database path or sqlite:/// URL. Defaults to AGILEFORGE_DB_URL.",  # noqa: E501
    )
    args = parser.parse_args()
    dry_run_validation(args.product_id, db=args.db)
