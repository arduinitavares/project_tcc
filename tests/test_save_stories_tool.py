"""Tests for save_stories_tool: validation error handling.

Covers the bug where Pydantic model-level validators produce errors with
an empty ``loc`` tuple, causing ``IndexError: tuple index out of range``
inside the error formatting code.
"""

import pytest
from sqlmodel import Session

from agile_sqlmodel import Product
from orchestrator_agent.agent_tools.user_story_writer_tool.tools import (
    SaveStoriesInput,
    save_stories_tool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_product(session: Session, product_id: int = 7) -> Product:
    """Insert a minimal Product row and return it."""
    product = Product(
        product_id=product_id,
        name="Test Product",
        description="For testing save_stories_tool",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def _valid_story() -> dict:
    """Return a story dict that passes all UserStoryItem validations."""
    return {
        "story_title": "Enforce attestation gate",
        "statement": (
            "As a System Admin, I want persistence blocked without attestation, "
            "so that no document is persisted without explicit consent."
        ),
        "acceptance_criteria": [
            "Verify that persistence is blocked when attestation is false."
        ],
        "invest_score": "High",
    }


def _story_missing_so_that() -> dict:
    """Return a story whose statement is missing 'so that' – triggers model validator."""
    return {
        "story_title": "Prevent storing confirmations with snapshots",
        "statement": (
            "As a Compliance Officer, I want the system to prevent "
            "user confirmation data from being stored together with document snapshots."
        ),
        "acceptance_criteria": [
            "Verify that persisted snapshots do not contain user confirmation fields."
        ],
        "invest_score": "High",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSaveStoriesTool:
    """Validation and persistence tests for save_stories_tool."""

    def test_model_validator_empty_loc_does_not_crash(self, session: Session):
        """Regression: model-level validator errors have loc=() which caused
        IndexError when formatting the error message."""
        _seed_product(session)

        payload = SaveStoriesInput(
            product_id=7,
            parent_requirement="Attestation Gate",
            stories=[_story_missing_so_that()],
        )
        result = save_stories_tool(input_data=payload, tool_context=None)

        # Should return a structured error, NOT crash
        assert result["success"] is False
        assert "error" in result
        assert "so that" in result["error"].lower() or "validation" in result["error"].lower()

    def test_mixed_valid_and_invalid_stories(self, session: Session):
        """When some stories pass and some fail model validation,
        the tool must report failure without crashing."""
        _seed_product(session)

        payload = SaveStoriesInput(
            product_id=7,
            parent_requirement="Attestation Gate",
            stories=[_valid_story(), _story_missing_so_that()],
        )
        result = save_stories_tool(input_data=payload, tool_context=None)

        assert result["success"] is False
        assert result["valid_count"] == 1
        assert result["invalid_count"] == 1

    def test_valid_stories_are_saved(self, session: Session):
        """Happy path: valid stories are persisted and IDs returned."""
        _seed_product(session)

        payload = SaveStoriesInput(
            product_id=7,
            parent_requirement="Attestation Gate",
            stories=[_valid_story()],
        )
        result = save_stories_tool(input_data=payload, tool_context=None)

        assert result["success"] is True
        assert result["saved_count"] == 1
        assert len(result["story_ids"]) == 1

    def test_nonexistent_product_returns_error(self, session: Session):
        """Calling with a product_id that does not exist returns structured error."""
        payload = SaveStoriesInput(
            product_id=999,
            parent_requirement="N/A",
            stories=[_valid_story()],
        )
        result = save_stories_tool(input_data=payload, tool_context=None)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_extra_field_rejected(self, session: Session):
        """UserStoryItem has extra='forbid'; story with unknown keys must fail validation."""
        _seed_product(session)

        story = _valid_story()
        story["unknown_field"] = "should be rejected"

        payload = SaveStoriesInput(
            product_id=7,
            parent_requirement="Attestation Gate",
            stories=[story],
        )
        result = save_stories_tool(input_data=payload, tool_context=None)

        assert result["success"] is False
        assert "error" in result

    def test_empty_stories_list_handled(self, session: Session):
        """An empty story list should fail gracefully (no crash)."""
        _seed_product(session)

        payload = SaveStoriesInput(
            product_id=7,
            parent_requirement="Attestation Gate",
            stories=[],
        )
        result = save_stories_tool(input_data=payload, tool_context=None)

        # Should succeed with 0 saved (no stories to persist)
        # OR return a validation error — either way, must not crash
        assert isinstance(result, dict)
        assert "success" in result
