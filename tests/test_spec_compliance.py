"""
Tests for Spec Compliance Logic
"""

import pytest
import json
from unittest.mock import MagicMock
from orchestrator_agent.agent_tools.story_pipeline.story_refiner_agent.agent import exit_loop
from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import SpecValidationResult, SPEC_VALIDATOR_INSTRUCTION, spec_validator_agent
from orchestrator_agent.agent_tools.story_pipeline.pipeline import story_sequential_pipeline

class MockToolContext:
    """Mock Google ADK ToolContext"""
    def __init__(self, state: dict):
        self.state = state
        self.actions = MagicMock()
        self.actions.escalate = False

class TestRefinerExitLoopBlocking:
    """
    Verify that the refiner's exit_loop tool correctly blocks when
    spec validation fails, ensuring the 'gate' works.
    """

    def test_exit_loop_blocks_on_spec_violation(self):
        """
        GIVEN: INVEST score is high (95) and no INVEST suggestions
        BUT: Spec validation has suggestions (violation)
        WHEN: exit_loop is called
        THEN: It returns loop_exit=False and explains why
        """
        # Arrange
        state = {
            "validation_result": json.dumps({
                "is_valid": True,
                "validation_score": 95,
                "suggestions": []  # INVEST is happy
            }),
            "spec_validation_result": json.dumps({
                "is_compliant": False,
                "issues": ["Violation 1"],
                "suggestions": ["Fix Violation 1"]  # Spec is NOT happy
            })
        }
        context = MockToolContext(state)

        # Act
        result = exit_loop(context)

        # Assert
        assert result["loop_exit"] is False
        # It catches compliance check first
        assert "not compliant" in result.get("reason", "") or "suggestions remain" in result.get("reason", "")
        assert context.actions.escalate is False

    def test_exit_loop_blocks_on_spec_non_compliant_no_suggestions(self):
        """
        GIVEN: INVEST score high, Spec suggestions empty
        BUT: is_compliant is False (weird case, but possible)
        WHEN: exit_loop is called
        THEN: It returns loop_exit=False
        """
        # Arrange
        state = {
            "validation_result": json.dumps({
                "is_valid": True,
                "validation_score": 95,
                "suggestions": []
            }),
            "spec_validation_result": json.dumps({
                "is_compliant": False,
                "issues": ["Violation 1"],
                "suggestions": []  # Empty suggestions but compliant is False
            })
        }
        context = MockToolContext(state)

        # Act
        result = exit_loop(context)

        # Assert
        assert result["loop_exit"] is False
        assert "not compliant" in result["reason"]

    def test_exit_loop_allows_exit_when_both_compliant(self):
        """
        GIVEN: INVEST score high, no suggestions
        AND: Spec compliant, no suggestions
        WHEN: exit_loop is called
        THEN: It returns loop_exit=True
        """
        # Arrange
        state = {
            "validation_result": json.dumps({
                "is_valid": True,
                "validation_score": 95,
                "suggestions": []
            }),
            "spec_validation_result": json.dumps({
                "is_compliant": True,
                "issues": [],
                "suggestions": []
            })
        }
        context = MockToolContext(state)

        # Act
        result = exit_loop(context)

        # Assert
        assert result["loop_exit"] is True
        assert "validated successfully" in result["reason"]
        assert context.actions.escalate is True

    def test_exit_loop_blocks_on_invest_suggestions_even_if_spec_ok(self):
        """
        GIVEN: Spec is compliant
        BUT: INVEST has suggestions
        WHEN: exit_loop is called
        THEN: It returns loop_exit=False
        """
        # Arrange
        state = {
            "validation_result": json.dumps({
                "is_valid": True,
                "validation_score": 85,
                "suggestions": ["Improve description"]
            }),
            "spec_validation_result": json.dumps({
                "is_compliant": True,
                "issues": [],
                "suggestions": []
            })
        }
        context = MockToolContext(state)

        # Act
        result = exit_loop(context)

        # Assert
        assert result["loop_exit"] is False
        assert "INVEST suggestions remain" in result["reason"]


class TestSpecValidatorConfiguration:
    """Verify SpecValidatorAgent configuration and instruction correctness."""

    def test_instruction_contains_default_compliant_rule(self):
        """Instruction must tell LLM to default to compliant if spec is empty."""
        assert "If `technical_spec` is EMPTY" in SPEC_VALIDATOR_INSTRUCTION
        assert "is_compliant: true" in SPEC_VALIDATOR_INSTRUCTION

    def test_instruction_emphasizes_explicit_violations(self):
        """Instruction must emphasize explicit constraints (must/shall)."""
        assert "EXPLICIT" in SPEC_VALIDATOR_INSTRUCTION
        assert "MUST" in SPEC_VALIDATOR_INSTRUCTION
        assert "SHALL" in SPEC_VALIDATOR_INSTRUCTION

    def test_schema_allows_empty_suggestions(self):
        """Verify the Pydantic model allows empty lists."""
        result = SpecValidationResult(
            is_compliant=True,
            issues=[],
            suggestions=[],
            verdict="All good"
        )
        assert result.is_compliant is True
        assert result.suggestions == []

    def test_pipeline_wiring(self):
        """Verify the agent is correctly inserted into the pipeline."""
        # Check sub_agents list
        agents = story_sequential_pipeline.sub_agents
        agent_names = [a.name for a in agents]

        assert "SpecValidatorAgent" in agent_names

        # Verify order: Invest -> Spec -> Refiner
        # Note: Index check assumes these are the exact names
        invest_idx = agent_names.index("InvestValidatorAgent")
        spec_idx = agent_names.index("SpecValidatorAgent")
        refiner_idx = agent_names.index("StoryRefinerAgent")

        assert invest_idx < spec_idx < refiner_idx

        # Verify agent configuration
        assert spec_validator_agent.output_key == "spec_validation_result"
        assert spec_validator_agent.output_schema == SpecValidationResult
