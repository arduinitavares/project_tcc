"""
Unit tests for SpecValidatorAgent Pydantic schema validation and retry logic.

These tests verify that the Pydantic V2 field validators correctly enforce
logical consistency and raise appropriate errors that trigger LLM retries.
"""

import pytest
from pydantic import ValidationError
from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import (
    SpecValidationResult,
)


class TestSpecValidationResultSchema:
    """Test suite for SpecValidationResult Pydantic model validators."""

    def test_compliant_story_with_empty_lists_valid(self):
        """Valid: Compliant story with no issues or suggestions."""
        result = SpecValidationResult(
            is_compliant=True,
            issues=[],
            suggestions=[],
            verdict="No technical spec provided"
        )
        assert result.is_compliant is True
        assert result.issues == []
        assert result.suggestions == []

    def test_compliant_story_with_issues_raises_error(self):
        """Invalid: Compliant=True but issues list is not empty."""
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,
                issues=["Database mismatch"],  # Violation: should be empty
                suggestions=[],
                verdict="Story is compliant"
            )
        
        # Verify the error message guides the LLM to fix the issue
        error_msg = str(exc_info.value)
        assert "Logical inconsistency" in error_msg
        assert "is_compliant=True" in error_msg
        assert "issues is not empty" in error_msg

    def test_compliant_story_with_suggestions_raises_error(self):
        """Invalid: Compliant=True but suggestions list is not empty."""
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,
                issues=[],
                suggestions=["Change database to PostgreSQL"],  # Violation: should be empty
                verdict="Story is compliant"
            )
        
        error_msg = str(exc_info.value)
        assert "Logical inconsistency" in error_msg
        assert "is_compliant=True" in error_msg
        assert "suggestions is not empty" in error_msg

    def test_compliant_story_with_both_issues_and_suggestions_raises_error(self):
        """Invalid: Compliant=True but both issues and suggestions are populated."""
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,
                issues=["Database mismatch"],
                suggestions=["Change to PostgreSQL"],
                verdict="Story is compliant"
            )
        
        # Should raise error for issues first (validator runs in order)
        error_msg = str(exc_info.value)
        assert "Logical inconsistency" in error_msg
        assert "is_compliant=True" in error_msg

    def test_non_compliant_story_with_issues_valid(self):
        """Valid: Non-compliant story with issues listed."""
        result = SpecValidationResult(
            is_compliant=False,
            issues=["System MUST use PostgreSQL but story mentions MongoDB"],
            suggestions=["Change database technology from MongoDB to PostgreSQL"],
            verdict="Story violates spec requirement in Section 3.2"
        )
        assert result.is_compliant is False
        assert len(result.issues) == 1
        assert len(result.suggestions) == 1

    def test_non_compliant_story_without_issues_raises_error(self):
        """Invalid: Non-compliant=False but issues list is empty."""
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=False,
                issues=[],  # Violation: must have at least one issue
                suggestions=["Fix the problem"],
                verdict="Story is non-compliant"
            )
        
        error_msg = str(exc_info.value)
        assert "Logical inconsistency" in error_msg
        assert "is_compliant=False" in error_msg
        assert "issues list is empty" in error_msg
        assert "specify at least one issue" in error_msg

    def test_non_compliant_story_with_empty_suggestions_valid(self):
        """Valid: Non-compliant story can have empty suggestions (optional guidance)."""
        result = SpecValidationResult(
            is_compliant=False,
            issues=["Missing required artifact"],
            suggestions=[],  # Suggestions are optional for non-compliant stories
            verdict="Story violates spec"
        )
        assert result.is_compliant is False
        assert len(result.issues) == 1
        assert result.suggestions == []

    def test_multiple_issues_and_suggestions(self):
        """Valid: Non-compliant story with multiple issues and suggestions."""
        result = SpecValidationResult(
            is_compliant=False,
            issues=[
                "Database technology violation",
                "Missing required security artifact",
                "API response format incorrect"
            ],
            suggestions=[
                "Change from MongoDB to PostgreSQL",
                "Add security audit log per Section 4.1",
                "Return JSON instead of XML"
            ],
            verdict="Multiple spec violations detected"
        )
        assert result.is_compliant is False
        assert len(result.issues) == 3
        assert len(result.suggestions) == 3

    def test_verdict_field_required(self):
        """Verdict field is required and cannot be omitted."""
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,
                issues=[],
                suggestions=[]
                # verdict is missing
            )
        
        error_msg = str(exc_info.value)
        assert "verdict" in error_msg.lower()

    def test_field_descriptions_accessible(self):
        """Verify field descriptions are available for LLM context."""
        schema = SpecValidationResult.model_json_schema()
        
        assert "is_compliant" in schema["properties"]
        assert "description" in schema["properties"]["is_compliant"]
        
        assert "issues" in schema["properties"]
        assert "description" in schema["properties"]["issues"]
        assert "Empty if compliant" in schema["properties"]["issues"]["description"]
        
        assert "suggestions" in schema["properties"]
        assert "Empty if compliant" in schema["properties"]["suggestions"]["description"]


class TestRetryLogicScenarios:
    """Test scenarios that would trigger LLM retries in production."""

    def test_scenario_llm_returns_compliant_with_hallucinated_issues(self):
        """
        Scenario: LLM correctly identifies compliance but hallucinates issues.
        Expected: Pydantic raises error, ADK retries with feedback.
        """
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,
                issues=["Some hallucinated issue"],  # LLM error
                suggestions=[],
                verdict="No spec violations"
            )
        
        assert "is_compliant=True but issues is not empty" in str(exc_info.value)

    def test_scenario_llm_returns_non_compliant_but_forgets_issues(self):
        """
        Scenario: LLM marks story as non-compliant but doesn't list issues.
        Expected: Pydantic raises error, ADK retries with feedback.
        """
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=False,
                issues=[],  # LLM forgot to list the issues
                suggestions=["Fix it"],
                verdict="Story violates spec"
            )
        
        assert "is_compliant=False but issues list is empty" in str(exc_info.value)

    def test_scenario_llm_confuses_compliant_status(self):
        """
        Scenario: LLM provides contradictory information.
        Expected: Pydantic catches the inconsistency.
        """
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,
                issues=[],
                suggestions=["You should fix this violation"],  # Contradictory
                verdict="Story is fine"
            )
        
        assert "Logical inconsistency" in str(exc_info.value)

    def test_scenario_valid_compliant_response(self):
        """
        Scenario: LLM correctly identifies no spec violations.
        Expected: Validation passes, no retry needed.
        """
        result = SpecValidationResult(
            is_compliant=True,
            issues=[],
            suggestions=[],
            verdict="No technical specification provided"
        )
        assert result.is_compliant is True

    def test_scenario_valid_non_compliant_response(self):
        """
        Scenario: LLM correctly identifies spec violations with details.
        Expected: Validation passes, no retry needed.
        """
        result = SpecValidationResult(
            is_compliant=False,
            issues=["System MUST use PostgreSQL but story uses MongoDB"],
            suggestions=["Change database technology to PostgreSQL per spec Section 3.2"],
            verdict="Database technology spec violation"
        )
        assert result.is_compliant is False
        assert len(result.issues) == 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_strings_in_lists_still_counts_as_populated(self):
        """Empty strings in issues/suggestions still violate the compliant=True rule."""
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,
                issues=[""],  # Empty string still counts as a list item
                suggestions=[],
                verdict="Compliant"
            )
        
        assert "is_compliant=True but issues is not empty" in str(exc_info.value)

    def test_whitespace_verdict_accepted(self):
        """Verdict can contain just whitespace (Pydantic allows it)."""
        result = SpecValidationResult(
            is_compliant=True,
            issues=[],
            suggestions=[],
            verdict="   "  # Just whitespace
        )
        assert result.verdict == "   "

    def test_long_lists_accepted(self):
        """Schema accepts arbitrarily long lists of issues/suggestions."""
        long_issues = [f"Issue {i}" for i in range(100)]
        long_suggestions = [f"Suggestion {i}" for i in range(100)]
        
        result = SpecValidationResult(
            is_compliant=False,
            issues=long_issues,
            suggestions=long_suggestions,
            verdict="Many violations"
        )
        assert len(result.issues) == 100
        assert len(result.suggestions) == 100


class TestDomainComplianceField:
    """Test the new domain_compliance field and its validators."""
    
    def test_domain_compliance_is_optional(self):
        """domain_compliance can be None (for stories without spec)."""
        result = SpecValidationResult(
            is_compliant=True,
            issues=[],
            suggestions=[],
            domain_compliance=None,
            verdict="No spec provided"
        )
        assert result.domain_compliance is None
    
    def test_domain_compliance_with_no_gaps_valid(self):
        """Valid: domain_compliance with empty critical_gaps when compliant."""
        from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import (
            DomainComplianceInfo,
        )
        
        result = SpecValidationResult(
            is_compliant=True,
            issues=[],
            suggestions=[],
            domain_compliance=DomainComplianceInfo(
                matched_domain="review",
                bound_requirement_count=3,
                satisfied_count=3,
                critical_gaps=[]
            ),
            verdict="All domain requirements satisfied"
        )
        assert result.is_compliant is True
        assert result.domain_compliance.matched_domain == "review"
    
    def test_domain_compliance_with_gaps_forces_non_compliant(self):
        """Invalid: is_compliant=True but domain_compliance has critical_gaps."""
        from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import (
            DomainComplianceInfo,
        )
        
        with pytest.raises(ValidationError) as exc_info:
            SpecValidationResult(
                is_compliant=True,  # Invalid: gaps exist
                issues=[],
                suggestions=[],
                domain_compliance=DomainComplianceInfo(
                    matched_domain="review",
                    bound_requirement_count=5,
                    satisfied_count=2,
                    critical_gaps=["review_actions artifact", "gold_primitives artifact"]
                ),
                verdict="Compliant"  # Contradicts critical_gaps
            )
        
        error_msg = str(exc_info.value)
        assert "Logical inconsistency" in error_msg
        assert "critical_gaps" in error_msg
    
    def test_domain_compliance_non_compliant_with_gaps_valid(self):
        """Valid: is_compliant=False when domain_compliance has critical_gaps."""
        from orchestrator_agent.agent_tools.story_pipeline.spec_validator_agent.agent import (
            DomainComplianceInfo,
        )
        
        result = SpecValidationResult(
            is_compliant=False,
            issues=["Missing review_actions artifact", "Missing gold_primitives artifact"],
            suggestions=["Add AC for review_actions_v{n}.jsonl", "Add AC for gold_primitives"],
            domain_compliance=DomainComplianceInfo(
                matched_domain="review",
                bound_requirement_count=5,
                satisfied_count=2,
                critical_gaps=["review_actions artifact", "gold_primitives artifact"]
            ),
            verdict="Domain requirements not satisfied"
        )
        assert result.is_compliant is False
        assert len(result.domain_compliance.critical_gaps) == 2
