"""
Tests for Spec Compliance Logic
"""

import pytest
import json
from unittest.mock import MagicMock
# exit_loop is removed, so we remove the import and the class testing it.
from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import SpecValidationResult, SPEC_VALIDATOR_INSTRUCTION, spec_validator_agent
from orchestrator_agent.agent_tools.story_pipeline.pipeline import story_sequential_pipeline

class TestSpecValidatorConfiguration:
    """Verify SpecValidatorAgent configuration and instruction correctness."""

    def test_instruction_contains_default_compliant_rule(self):
        """Instruction must tell LLM to default to compliant if spec is empty."""
        assert "If `technical_spec` is EMPTY" in SPEC_VALIDATOR_INSTRUCTION
        # Note: "is_compliant: true" string might have been removed during prompt cleanup (JSON removal).
        # We check for the concept logic instead.
        assert "mark the story as compliant" in SPEC_VALIDATOR_INSTRUCTION

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
        # sub_agents now contains SelfHealingAgent wrappers.
        # We need to unwrap or check names properly.
        # SelfHealingAgent.name is "SelfHealing_{inner_name}"

        agent_names = [a.name for a in agents]

        # Check for wrapped names
        assert "SelfHealing_SpecValidatorAgent" in agent_names

        # Verify order: Invest -> Spec -> Refiner
        invest_idx = agent_names.index("SelfHealing_InvestValidatorAgent")
        spec_idx = agent_names.index("SelfHealing_SpecValidatorAgent")
        refiner_idx = agent_names.index("SelfHealing_StoryRefinerAgent")

        assert invest_idx < spec_idx < refiner_idx

        # Verify agent configuration
        # spec_validator_agent is the inner agent instance
        assert spec_validator_agent.output_key == "spec_validation_result"
        assert spec_validator_agent.output_schema == SpecValidationResult
