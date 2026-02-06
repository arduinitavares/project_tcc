"""TDD tests for User Story Writer schemas."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from orchestrator_agent.agent_tools.user_story_writer_tool.schemes import (
    UserStoryItem,
    UserStoryWriterInput,
    UserStoryWriterOutput,
)


# ---------------------------------------------------------------------------
# UserStoryItem
# ---------------------------------------------------------------------------


class TestUserStoryItem:
    """Tests for the UserStoryItem schema."""

    def test_valid_high_score_item(self) -> None:
        item = UserStoryItem(
            story_title="Login via email",
            statement=(
                "As a registered member, I want to log in with my email, "
                "so that I can access my dashboard."
            ),
            acceptance_criteria=[
                "Verify that the login form accepts email and password.",
                "Verify that invalid credentials show an error message.",
                "Ensure that response time is under 500ms.",
            ],
            invest_score="High",
        )
        assert item.invest_score == "High"
        assert item.decomposition_warning is None

    def test_valid_medium_score_item(self) -> None:
        item = UserStoryItem(
            story_title="Export CSV report",
            statement=(
                "As a manager, I want to export a CSV report, "
                "so that I can analyze data offline."
            ),
            acceptance_criteria=["Verify that the CSV downloads correctly."],
            invest_score="Medium",
        )
        assert item.invest_score == "Medium"
        assert item.decomposition_warning is None

    def test_valid_low_score_with_warning(self) -> None:
        item = UserStoryItem(
            story_title="Batch data migration",
            statement=(
                "As a data engineer, I want to migrate legacy records, "
                "so that the new system has historical data."
            ),
            acceptance_criteria=["Verify that all records are transferred."],
            invest_score="Low",
            decomposition_warning="Hard dependency on legacy API availability.",
        )
        assert item.invest_score == "Low"
        assert "Hard dependency" in item.decomposition_warning

    def test_rejects_invalid_statement_missing_as_a(self) -> None:
        with pytest.raises(ValidationError, match="Statement must start with 'As a"):
            UserStoryItem(
                story_title="Bad story",
                statement="The user wants to log in so that they can access the app.",
                acceptance_criteria=["Verify login works."],
                invest_score="High",
            )

    def test_rejects_invalid_statement_missing_i_want(self) -> None:
        with pytest.raises(ValidationError, match="I want"):
            UserStoryItem(
                story_title="Bad story",
                statement="As a user, logging in, so that I can access my account.",
                acceptance_criteria=["Verify login works."],
                invest_score="High",
            )

    def test_rejects_invalid_statement_missing_so_that(self) -> None:
        with pytest.raises(ValidationError, match="so that"):
            UserStoryItem(
                story_title="Bad story",
                statement="As a user, I want to log in.",
                acceptance_criteria=["Verify login works."],
                invest_score="High",
            )

    def test_rejects_high_score_with_warning(self) -> None:
        with pytest.raises(ValidationError, match="must be omitted"):
            UserStoryItem(
                story_title="Some story title",
                statement="As a user, I want feature X, so that I get benefit Y.",
                acceptance_criteria=["Verify X works."],
                invest_score="High",
                decomposition_warning="Should not be here.",
            )

    def test_rejects_medium_score_with_warning(self) -> None:
        with pytest.raises(ValidationError, match="must be omitted"):
            UserStoryItem(
                story_title="Some story title",
                statement="As a user, I want feature X, so that I get benefit Y.",
                acceptance_criteria=["Verify X works."],
                invest_score="Medium",
                decomposition_warning="Should not be here either.",
            )

    def test_rejects_low_score_without_warning(self) -> None:
        with pytest.raises(
            ValidationError, match="required when invest_score is 'Low'"
        ):
            UserStoryItem(
                story_title="Some story title",
                statement="As a user, I want feature X, so that I get benefit Y.",
                acceptance_criteria=["Verify X works."],
                invest_score="Low",
            )

    def test_rejects_empty_acceptance_criteria(self) -> None:
        with pytest.raises(ValidationError):
            UserStoryItem(
                story_title="Some story title",
                statement="As a user, I want feature X, so that I get benefit Y.",
                acceptance_criteria=[],
                invest_score="High",
            )

    def test_json_round_trip(self) -> None:
        item = UserStoryItem(
            story_title="Upload CSV file",
            statement=(
                "As a data analyst, I want to upload a CSV file, "
                "so that I can visualize data."
            ),
            acceptance_criteria=[
                "Verify that CSV files up to 10MB are accepted.",
                "Ensure that upload completes within 3 seconds.",
            ],
            invest_score="Medium",
        )
        dumped = item.model_dump_json()
        loaded = UserStoryItem.model_validate_json(dumped)
        assert loaded.story_title == item.story_title
        assert loaded.acceptance_criteria == item.acceptance_criteria
        assert loaded.decomposition_warning is None

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            UserStoryItem(
                story_title="Valid title here",
                statement="As a user, I want feature X, so that I get benefit Y.",
                acceptance_criteria=["Verify X."],
                invest_score="High",
                unknown_field="bad",
            )


# ---------------------------------------------------------------------------
# UserStoryWriterInput
# ---------------------------------------------------------------------------


class TestUserStoryWriterInput:
    """Tests for the input schema."""

    def test_valid_input(self) -> None:
        inp = UserStoryWriterInput(
            parent_requirement="Offline Dataset Ingestion",
            requirement_context="Must support CSV and Parquet formats.",
            technical_spec="Max file size 500MB. Processing within 60s.",
            compiled_authority="ISO 27001 compliance required.",
        )
        assert inp.parent_requirement == "Offline Dataset Ingestion"

    def test_accepts_extra_fields_for_adk_compat(self) -> None:
        """ADK input schemas must NOT use extra='forbid'."""
        inp = UserStoryWriterInput(
            parent_requirement="Valid requirement name",
            requirement_context="context",
            technical_spec="spec",
            compiled_authority="auth",
            extra_field="tolerated",
        )
        assert inp.parent_requirement == "Valid requirement name"

    def test_json_round_trip(self) -> None:
        payload: Dict[str, Any] = {
            "parent_requirement": "User Authentication",
            "requirement_context": "Critical for security.",
            "technical_spec": "OAuth2 + MFA required.",
            "compiled_authority": "SOC2 Type II.",
        }
        model = UserStoryWriterInput.model_validate(payload)
        dumped = model.model_dump_json()
        loaded = UserStoryWriterInput.model_validate_json(dumped)
        assert loaded.parent_requirement == payload["parent_requirement"]


# ---------------------------------------------------------------------------
# UserStoryWriterOutput
# ---------------------------------------------------------------------------


class TestUserStoryWriterOutput:
    """Tests for the output schema."""

    def _make_valid_story(self, **overrides: Any) -> Dict[str, Any]:
        """Helper: build a valid UserStoryItem dict."""
        base: Dict[str, Any] = {
            "story_title": "Upload CSV file",
            "statement": (
                "As a data engineer, I want to upload a CSV file, "
                "so that raw data enters the system."
            ),
            "acceptance_criteria": ["Verify that CSV is parsed correctly."],
            "invest_score": "High",
        }
        base.update(overrides)
        return base

    def test_valid_complete_output(self) -> None:
        out = UserStoryWriterOutput(
            parent_requirement="Offline Dataset Ingestion",
            user_stories=[UserStoryItem(**self._make_valid_story())],
            is_complete=True,
        )
        assert out.is_complete is True
        assert len(out.user_stories) == 1
        assert out.clarifying_questions == []

    def test_valid_incomplete_output_with_questions(self) -> None:
        out = UserStoryWriterOutput(
            parent_requirement="Dashboard Analytics",
            user_stories=[
                UserStoryItem(
                    story_title="View sales chart",
                    statement=(
                        "As a manager, I want to view a sales chart, "
                        "so that I can track revenue."
                    ),
                    acceptance_criteria=["Verify chart renders."],
                    invest_score="High",
                ),
            ],
            is_complete=False,
            clarifying_questions=["What chart types are required?"],
        )
        assert out.is_complete is False
        assert len(out.clarifying_questions) == 1

    def test_rejects_empty_stories(self) -> None:
        with pytest.raises(ValidationError):
            UserStoryWriterOutput(
                parent_requirement="Something valid",
                user_stories=[],
                is_complete=True,
            )

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            UserStoryWriterOutput(
                parent_requirement="Valid requirement",
                user_stories=[UserStoryItem(**self._make_valid_story())],
                is_complete=True,
                bonus="bad",
            )

    def test_json_round_trip(self) -> None:
        out = UserStoryWriterOutput(
            parent_requirement="Authentication",
            user_stories=[
                UserStoryItem(
                    story_title="Login with email",
                    statement=(
                        "As a member, I want to log in, "
                        "so that I access my account."
                    ),
                    acceptance_criteria=["Verify login succeeds."],
                    invest_score="High",
                ),
            ],
            is_complete=True,
        )
        dumped = out.model_dump_json()
        loaded = UserStoryWriterOutput.model_validate_json(dumped)
        assert loaded.parent_requirement == "Authentication"
        assert len(loaded.user_stories) == 1
        # Verify no extra text (markdown fences, commentary)
        parsed = json.loads(dumped)
        assert "```" not in dumped
        assert set(parsed.keys()) == {
            "parent_requirement",
            "user_stories",
            "is_complete",
            "clarifying_questions",
        }
