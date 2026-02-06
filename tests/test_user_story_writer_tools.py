"""TDD tests for User Story Writer tools (unit-level)."""

from __future__ import annotations

from orchestrator_agent.agent_tools.user_story_writer_tool.tools import (
    _extract_persona,
)


class TestExtractPersona:
    """Tests for the _extract_persona helper."""

    def test_extracts_simple_role(self) -> None:
        statement = (
            "As a data engineer, I want to upload files, "
            "so that data is ingested."
        )
        assert _extract_persona(statement) == "data engineer"

    def test_extracts_role_with_article_an(self) -> None:
        statement = (
            "As an admin, I want to manage users, "
            "so that access is controlled."
        )
        assert _extract_persona(statement) == "admin"

    def test_returns_none_for_invalid_format(self) -> None:
        assert _extract_persona("The user wants to log in.") is None

    def test_extracts_multi_word_role(self) -> None:
        statement = (
            "As a compliance officer, I want to review audit logs, "
            "so that we meet regulations."
        )
        assert _extract_persona(statement) == "compliance officer"

    def test_extracts_role_with_adjective(self) -> None:
        statement = (
            "As a frequent traveler, I want to save preferences, "
            "so that booking is faster."
        )
        assert _extract_persona(statement) == "frequent traveler"

    def test_returns_none_for_empty_string(self) -> None:
        assert _extract_persona("") is None
