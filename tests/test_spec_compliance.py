"""
Tests for Spec Compliance Logic
"""

import pytest
import json
from unittest.mock import MagicMock
# exit_loop is removed, so we remove the import and the class testing it.
from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import SpecValidationResult, spec_validator_agent
from orchestrator_agent.agent_tools.story_pipeline.pipeline import story_sequential_pipeline

class TestSpecValidatorConfiguration:
    """Verify SpecValidatorAgent configuration and instruction correctness."""

    def test_instruction_contains_default_compliant_rule(self):
        """Instruction must tell LLM to default to compliant if spec is empty."""
        instruction = spec_validator_agent.instruction
        # Updated: The new instruction uses "NO TECHNICAL_SPEC or EMPTY SPEC" section
        assert "NO TECHNICAL_SPEC" in instruction or "EMPTY SPEC" in instruction
        # Check for the concept that empty spec = compliant
        assert "is_compliant: true" in instruction or "compliant by default" in instruction

    def test_instruction_emphasizes_explicit_violations(self):
        """Instruction must emphasize explicit constraints (must/shall)."""
        instruction = spec_validator_agent.instruction
        # Updated: New instruction uses domain-aware validation with explicit requirement keywords
        assert "MUST" in instruction
        assert "SHALL" in instruction
        # The new instruction emphasizes domain requirements instead of just EXPLICIT
        assert "REQUIRED" in instruction or "requirement" in instruction.lower()

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

        # Verify order: Draft -> Spec -> Refiner (INVEST removed - built into Draft)
        draft_idx = agent_names.index("SelfHealing_StoryDraftAgent")
        spec_idx = agent_names.index("SelfHealing_SpecValidatorAgent")
        refiner_idx = agent_names.index("SelfHealing_StoryRefinerAgent")

        assert draft_idx < spec_idx < refiner_idx

        # Verify agent configuration
        # spec_validator_agent is the inner agent instance
        assert spec_validator_agent.output_key == "spec_validation_result"
        assert spec_validator_agent.output_schema == SpecValidationResult
