"""Tests for the story validation backfill CLI."""

from __future__ import annotations

import io
import logging
import os
from contextlib import redirect_stderr
from typing import TYPE_CHECKING

import pytest

from agile_sqlmodel import Product, SpecRegistry, UserStory

os.environ.setdefault("ALLOW_PROD_DB_IN_TEST", "1")

from scripts import apply_story_validation as validation_script
from utils.runtime_config import clear_runtime_config_cache

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlmodel import Session


def _remove_console_handlers() -> None:
    root_logger = logging.getLogger()
    kept_handlers = []
    for handler in root_logger.handlers:
        handler_id = getattr(handler, "_agileforge_handler_id", "")
        if str(handler_id).startswith("console:"):
            handler.close()
            continue
        kept_handlers.append(handler)
    root_logger.handlers = kept_handlers


@pytest.fixture(autouse=True)
def _reset_console_logging(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
) -> Iterator[None]:
    monkeypatch.setattr(validation_script, "engine", engine)
    _remove_console_handlers()
    clear_runtime_config_cache()
    yield
    _remove_console_handlers()
    clear_runtime_config_cache()


def _seed_product_with_stories(
    session: Session,
    *,
    refined_story_count: int = 2,
    include_unrefined: bool = False,
    include_spec: bool = True,
) -> tuple[int, list[int]]:
    product = Product(name="Validation Product")
    session.add(product)
    session.commit()
    session.refresh(product)
    assert product.product_id is not None

    if include_spec:
        session.add(
            SpecRegistry(
                product_id=product.product_id,
                spec_hash="abc123",
                content="# Approved Spec",
                status="approved",
            )
        )

    story_ids: list[int] = []
    for idx in range(refined_story_count):
        story = UserStory(
            product_id=product.product_id,
            title=f"Story {idx + 1}",
            story_description="As a user, I want concise validation logs.",
            acceptance_criteria="- Given a story\n- When validation runs\n- Then evidence is stored",  # noqa: E501
            is_refined=True,
            is_superseded=False,
        )
        session.add(story)
        session.flush()
        assert story.story_id is not None
        story_ids.append(story.story_id)

    if include_unrefined:
        session.add(
            UserStory(
                product_id=product.product_id,
                title="Unrefined story",
                story_description="Draft only",
                acceptance_criteria="- TBD",
                is_refined=False,
                is_superseded=False,
            )
        )

    session.commit()
    return product.product_id, story_ids


def test_default_cli_output_is_concise(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    """Verify default cli output is concise."""
    product_id, story_ids = _seed_product_with_stories(session, include_unrefined=True)

    def fake_validate(payload: dict[str, object]) -> dict[str, object]:
        if payload["story_id"] == story_ids[0]:
            return {
                "success": True,
                "passed": True,
                "failures": [],
                "alignment_failures": [],
                "message": "Validation passed",
            }
        return {
            "success": True,
            "passed": False,
            "failures": [
                {
                    "rule": "RULE_ACCEPTANCE_CRITERIA_REQUIRED",
                    "actual": "Acceptance criteria reference missing field",
                    "message": "Missing acceptance criteria",
                }
            ],
            "alignment_failures": [
                {
                    "code": "FORBIDDEN_CAPABILITY",
                    "message": "Story references forbidden capability",
                    "invariant": "INV-1234567890abcdef",
                }
            ],
            "message": "Validation failed with 2 issue(s)",
        }

    monkeypatch.setattr(
        validation_script, "validate_story_with_spec_authority", fake_validate
    )

    stream = io.StringIO()
    with redirect_stderr(stream):
        exit_code = validation_script.main([str(product_id)])

    output = stream.getvalue()
    assert exit_code == 0
    assert (
        f"Applying validation to Product {product_id} 'Validation Product'." in output
    )
    assert "Validation mode: deterministic" in output
    assert "Found 2 eligible refined stories." in output
    assert "Validated 2 stories: 1 passed, 1 failed" in output
    assert f"Story {story_ids[0]}: PASS" not in output
    assert "RULE_ACCEPTANCE_CRITERIA_REQUIRED" not in output
    assert "FORBIDDEN_CAPABILITY" not in output
    assert "SELECT " not in output


def test_verbose_cli_output_includes_story_details(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    """Verify verbose cli output includes story details."""
    product_id, story_ids = _seed_product_with_stories(session)

    def fake_validate(payload: dict[str, object]) -> dict[str, object]:
        if payload["story_id"] == story_ids[0]:
            return {
                "success": True,
                "passed": True,
                "failures": [],
                "alignment_failures": [],
                "message": "Validation passed",
            }
        return {
            "success": True,
            "passed": False,
            "failures": [
                {
                    "rule": "RULE_ACCEPTANCE_CRITERIA_REQUIRED",
                    "actual": "Acceptance criteria reference missing field",
                    "message": "Missing acceptance criteria",
                }
            ],
            "alignment_failures": [
                {
                    "code": "FORBIDDEN_CAPABILITY",
                    "message": "Story references forbidden capability",
                    "invariant": "INV-1234567890abcdef",
                }
            ],
            "message": "Validation failed with 2 issue(s)",
        }

    monkeypatch.setattr(
        validation_script, "validate_story_with_spec_authority", fake_validate
    )

    stream = io.StringIO()
    with redirect_stderr(stream):
        exit_code = validation_script.main([str(product_id), "--verbose"])

    output = stream.getvalue()
    assert exit_code == 0
    assert f"Story {story_ids[0]}: PASS" in output
    assert f"Story {story_ids[1]}: FAIL" in output
    assert (
        "RULE_ACCEPTANCE_CRITERIA_REQUIRED: Acceptance criteria reference missing field"
        in output
    )
    assert (
        "FORBIDDEN_CAPABILITY (INV-1234567890abcdef): Story references forbidden capability"  # noqa: E501
        in output
    )


def test_quiet_cli_output_suppresses_routine_progress(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    """Verify quiet cli output suppresses routine progress."""
    product_id, _story_ids = _seed_product_with_stories(session)

    monkeypatch.setattr(
        validation_script,
        "validate_story_with_spec_authority",
        lambda payload: {  # noqa: ARG005
            "success": True,
            "passed": True,
            "failures": [],
            "alignment_failures": [],
            "message": "Validation passed",
        },
    )

    stream = io.StringIO()
    with redirect_stderr(stream):
        exit_code = validation_script.main([str(product_id), "--quiet"])

    output = stream.getvalue()
    assert exit_code == 0
    assert "Applying validation to Product" not in output
    assert "Validation mode:" not in output
    assert "Found 2 eligible refined stories." not in output
    assert "Validated 2 stories: 2 passed, 0 failed" in output


def test_no_refined_stories_is_a_clear_noop(session: Session) -> None:
    """Verify no refined stories is a clear noop."""
    product_id, _story_ids = _seed_product_with_stories(
        session,
        refined_story_count=0,
        include_unrefined=True,
    )

    stream = io.StringIO()
    with redirect_stderr(stream):
        exit_code = validation_script.main([str(product_id)])

    assert exit_code == 0
    assert (
        f"No refined stories found for product {product_id}. Nothing to validate."
        in stream.getvalue()
    )


def test_missing_approved_spec_returns_non_zero(session: Session) -> None:
    """Verify missing approved spec returns non zero."""
    product_id, _story_ids = _seed_product_with_stories(session, include_spec=False)

    stream = io.StringIO()
    with redirect_stderr(stream):
        exit_code = validation_script.main([str(product_id)])

    assert exit_code == 1
    assert f"No approved spec found for product {product_id}." in stream.getvalue()
