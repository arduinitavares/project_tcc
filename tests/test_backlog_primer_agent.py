"""Schema tests for backlog_primer agent outputs."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from orchestrator_agent.agent_tools.backlog_primer.schemes import (
    BacklogItem,
    InputSchema,
    OutputSchema,
)
from orchestrator_agent.agent_tools.backlog_primer.tools import (
    SaveBacklogInput,
    save_backlog_tool,
)


class TestBacklogPrimerSchemas:
    """Validate input/output schema rules."""

    def test_input_schema_json_roundtrip(self) -> None:
        payload: dict[str, Any] = {
            "product_vision_statement": "For teams who need clarity...",
            "technical_spec": "Spec: must support SSO and audit logging.",
            "compiled_authority": "{\"scope_themes\":[\"Auth\"],\"invariants\":[]}",
            "prior_backlog_state": "NO_HISTORY",
            "user_input": "Focus on onboarding and analytics.",
        }
        parsed = InputSchema.model_validate_json(json.dumps(payload))
        assert parsed.product_vision_statement.startswith("For teams")

    def test_output_schema_valid_payload(self) -> None:
        payload: dict[str, Any] = {
            "backlog_items": [
                {
                    "priority": 1,
                    "requirement": "User onboarding and account setup",
                    "value_driver": "Customer Satisfaction",
                    "justification": "Unlocks first-time user value",
                    "estimated_effort": "M",
                    "technical_note": "Requires SSO and audit logging.",
                },
                {
                    "priority": 2,
                    "requirement": "Core workflow management",
                    "value_driver": "Revenue",
                    "justification": "Delivers primary business outcome",
                    "estimated_effort": "L",
                    "technical_note": None,
                },
            ],
            "is_complete": False,
            "clarifying_questions": [
                "Which user segment should be prioritized first?"
            ],
        }

        parsed = OutputSchema.model_validate_json(json.dumps(payload))
        assert len(parsed.backlog_items) == 2

    def test_backlog_item_rejects_invalid_effort(self) -> None:
        with pytest.raises(ValidationError):
            BacklogItem(
                priority=1,
                requirement="Notifications",
                value_driver="Strategic",
                justification="Boosts engagement",
                estimated_effort="XXL",  # type: ignore[arg-type]
                technical_note=None,
            )

    def test_backlog_item_requires_positive_priority(self) -> None:
        with pytest.raises(ValidationError):
            BacklogItem(
                priority=0,
                requirement="Security baseline",
                value_driver="Strategic",
                justification="Reduces compliance risk",
                estimated_effort="M",
                technical_note=None,
            )


class TestSaveBacklogTool:
    """Tests for save_backlog_tool."""

    @pytest.mark.asyncio
    async def test_save_backlog_stores_in_session_state(self) -> None:
        """Valid backlog items are stored in session state."""
        mock_context = MagicMock()
        mock_context.state = {}

        save_input = SaveBacklogInput(
            product_id=1,
            backlog_items=[
                {
                    "priority": 1,
                    "requirement": "User authentication",
                    "value_driver": "Customer Satisfaction",
                    "justification": "Security baseline",
                    "estimated_effort": "M",
                },
                {
                    "priority": 2,
                    "requirement": "Dashboard analytics",
                    "value_driver": "Revenue",
                    "justification": "Drives engagement",
                    "estimated_effort": "L",
                },
            ],
        )

        result = await save_backlog_tool(save_input, tool_context=mock_context)

        assert result["success"] is True
        assert result["saved_count"] == 2
        assert "approved_backlog" in mock_context.state
        assert mock_context.state["approved_backlog"]["product_id"] == 1
        assert len(mock_context.state["approved_backlog"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_save_backlog_rejects_invalid_items(self) -> None:
        """Invalid backlog items fail validation."""
        mock_context = MagicMock()
        mock_context.state = {}

        save_input = SaveBacklogInput(
            product_id=1,
            backlog_items=[
                {
                    "priority": 1,
                    # Missing: requirement, value_driver, justification, estimated_effort
                },
            ],
        )

        result = await save_backlog_tool(save_input, tool_context=mock_context)

        assert result["success"] is False
        assert "Validation errors" in result["error"]

    @pytest.mark.asyncio
    async def test_save_backlog_requires_tool_context(self) -> None:
        """Tool returns error when tool_context is None."""
        save_input = SaveBacklogInput(
            product_id=1,
            backlog_items=[
                {
                    "priority": 1,
                    "requirement": "Test",
                    "value_driver": "Revenue",
                    "justification": "Test",
                    "estimated_effort": "S",
                },
            ],
        )

        result = await save_backlog_tool(save_input, tool_context=None)

        assert result["success"] is False
        assert "ToolContext required" in result["error"]
