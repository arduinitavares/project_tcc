"""
Tests for story_contract_enforcer.py - deterministic final validation stage.
"""

import pytest
from orchestrator_agent.agent_tools.story_pipeline.story_contract_enforcer import (
    enforce_story_contracts,
    enforce_story_points_contract,
    enforce_persona_contract,
    enforce_scope_contract,
    enforce_invest_result_presence,
    enforce_feature_id_consistency,
    enforce_validator_state_consistency,
    format_contract_violations,
)


class TestStoryPointsContract:
    """Test Rule 1: Story points contract."""

    def test_points_forbidden_but_present(self):
        """Story has points when include_story_points=False -> violation."""
        story = {"story_points": 5}
        violation = enforce_story_points_contract(story, include_story_points=False)

        assert violation is not None
        assert violation.rule == "STORY_POINTS_FORBIDDEN"
        assert violation.expected is None
        assert violation.actual == 5

    def test_points_forbidden_and_null(self):
        """Story has NULL points when include_story_points=False -> OK."""
        story = {"story_points": None}
        violation = enforce_story_points_contract(story, include_story_points=False)

        assert violation is None

    def test_points_allowed_and_present(self):
        """Story has valid points when include_story_points=True -> OK."""
        story = {"story_points": 3}
        violation = enforce_story_points_contract(story, include_story_points=True)

        assert violation is None

    def test_points_out_of_range(self):
        """Story has invalid point value (not 1-8) -> violation."""
        story = {"story_points": 10}
        violation = enforce_story_points_contract(story, include_story_points=True)

        assert violation is not None
        assert violation.rule == "STORY_POINTS_OUT_OF_RANGE"
        assert violation.actual == 10


class TestPersonaContract:
    """Test Rule 2: Persona contract."""

    def test_persona_matches(self):
        """Story uses exact persona -> OK."""
        story = {
            "description": "As an automation engineer, I want to upload PDFs so that I can process them."
        }
        violation = enforce_persona_contract(story, expected_persona="automation engineer")

        assert violation is None

    def test_persona_matches_plural_vs_singular(self):
        """Story uses singular, expected is plural (or vice versa) -> OK after normalization."""
        story = {
            "description": "As a QA reviewer, I want to review documents so that quality is maintained."
        }
        violation = enforce_persona_contract(story, expected_persona="QA reviewers")

        assert violation is None  # Should pass after normalization

    def test_persona_matches_case_insensitive(self):
        """Story uses different case -> OK after normalization."""
        story = {
            "description": "As an Automation Engineer, I want to upload PDFs so that I can process them."
        }
        violation = enforce_persona_contract(story, expected_persona="automation engineer")

        assert violation is None

    def test_persona_mismatch(self):
        """Story uses wrong persona -> violation."""
        story = {
            "description": "As a software engineer, I want to upload PDFs so that I can process them."
        }
        violation = enforce_persona_contract(story, expected_persona="automation engineer")

        assert violation is not None
        assert violation.rule == "PERSONA_MISMATCH"
        assert violation.expected == "automation engineer"
        assert "software engineer" in violation.actual

    def test_persona_format_invalid_no_as_a(self):
        """Story doesn't start with 'As a' -> violation."""
        story = {"description": "I want to upload PDFs"}
        violation = enforce_persona_contract(story, expected_persona="automation engineer")

        assert violation is not None
        assert violation.rule == "PERSONA_FORMAT_INVALID"

    def test_persona_format_invalid_no_i_want(self):
        """Story doesn't contain ', I want' -> violation."""
        story = {"description": "As an automation engineer"}
        violation = enforce_persona_contract(story, expected_persona="automation engineer")

        assert violation is not None
        assert violation.rule == "PERSONA_FORMAT_INVALID"


class TestInvestResultPresence:
    """Test Rule 3a: INVEST result presence."""

    def test_invest_result_missing(self):
        """No validation_result -> violation."""
        violation = enforce_invest_result_presence(validation_result=None)

        assert violation is not None
        assert violation.rule == "INVEST_RESULT_MISSING"

    def test_invest_score_missing(self):
        """validation_result exists but no score -> violation."""
        violation = enforce_invest_result_presence(validation_result={})

        assert violation is not None
        assert violation.rule == "INVEST_SCORE_MISSING"

    def test_invest_score_zero(self):
        """Score is 0 (validation didn't run) -> violation."""
        violation = enforce_invest_result_presence(
            validation_result={"validation_score": 0}
        )

        assert violation is not None
        assert violation.rule == "INVEST_SCORE_ZERO"

    def test_invest_result_valid(self):
        """validation_result with non-zero score -> OK."""
        violation = enforce_invest_result_presence(
            validation_result={"validation_score": 85}
        )

        assert violation is None


class TestFeatureIdConsistency:
    """Test Rule 3b: Feature ID consistency."""

    def test_feature_id_missing(self):
        """Story has no feature_id -> violation."""
        story = {"title": "Test story"}
        violation = enforce_feature_id_consistency(story, expected_feature_id=42)

        assert violation is not None
        assert violation.rule == "FEATURE_ID_MISSING"
        assert violation.expected == 42

    def test_feature_id_mismatch(self):
        """Story feature_id != expected -> violation (data corruption risk)."""
        story = {"feature_id": 101}
        violation = enforce_feature_id_consistency(story, expected_feature_id=82)

        assert violation is not None
        assert violation.rule == "FEATURE_ID_MISMATCH"
        assert violation.expected == 82
        assert violation.actual == 101
        assert "data corruption" in violation.message.lower()

    def test_feature_id_matches(self):
        """Story feature_id == expected -> OK."""
        story = {"feature_id": 42}
        violation = enforce_feature_id_consistency(story, expected_feature_id=42)

        assert violation is None


class TestScopeContract:
    """Test Rule 3: Scope contract."""

    def test_scope_matches(self):
        """Feature time_frame matches allowed scope -> OK."""
        violation = enforce_scope_contract(feature_time_frame="Now", allowed_scope="Now")

        assert violation is None

    def test_scope_mismatch(self):
        """Feature time_frame doesn't match allowed scope -> violation."""
        violation = enforce_scope_contract(feature_time_frame="Next", allowed_scope="Now")

        assert violation is not None
        assert violation.rule == "SCOPE_MISMATCH"
        assert violation.expected == "Now"
        assert violation.actual == "Next"

    def test_scope_metadata_missing(self):
        """Feature time_frame is missing when scope filter is active -> violation."""
        violation = enforce_scope_contract(feature_time_frame=None, allowed_scope="Now")

        assert violation is not None
        assert violation.rule == "SCOPE_METADATA_MISSING"
        assert violation.expected == "Now"

    def test_no_scope_restriction(self):
        """No allowed_scope restriction -> OK regardless of time_frame."""
        violation = enforce_scope_contract(feature_time_frame="Later", allowed_scope=None)

        assert violation is None


class TestValidatorStateConsistency:
    """Test Rule 4: Validator state consistency."""
    
    def test_refinement_result_missing(self):
        """Refinement result missing -> violation."""
        violations = enforce_validator_state_consistency(
            validation_result={"validation_score": 95},
            spec_validation_result={"is_compliant": True},
            refinement_result=None,  # Missing
        )

        assert len(violations) == 1
        assert violations[0].rule == "REFINEMENT_RESULT_MISSING"

    def test_mixed_signals_invest_pass_spec_fail(self):
        """INVEST passed but spec failed -> violation."""
        validation_result = {"validation_score": 95}
        spec_validation_result = {"is_compliant": False}
        refinement_result = {"is_valid": False}

        violations = enforce_validator_state_consistency(
            validation_result, spec_validation_result, refinement_result
        )

        assert len(violations) == 1
        assert violations[0].rule == "MIXED_VALIDATION_SIGNALS"

    def test_leftover_suggestions_when_valid(self):
        """Story marked valid but suggestions remain -> violation."""
        validation_result = {"validation_score": 50}
        spec_validation_result = {
            "is_compliant": True,
            "suggestions": ["Add AC for doc_revision_id"],
        }
        refinement_result = {"is_valid": True}

        violations = enforce_validator_state_consistency(
            validation_result, spec_validation_result, refinement_result
        )

        assert len(violations) == 1
        assert violations[0].rule == "LEFTOVER_SUGGESTIONS"
        assert "1 spec suggestions" in violations[0].message

    def test_critical_gaps_when_valid(self):
        """Story marked valid but critical gaps remain -> violation."""
        validation_result = {"validation_score": 50}
        spec_validation_result = {
            "is_compliant": True,
            "domain_compliance": {
                "critical_gaps": ["doc_revision_id invariant", "input_hash requirement"]
            },
        }
        refinement_result = {"is_valid": True}

        violations = enforce_validator_state_consistency(
            validation_result, spec_validation_result, refinement_result
        )

        assert len(violations) == 1
        assert violations[0].rule == "UNRESOLVED_CRITICAL_GAPS"
        assert "2 critical domain gaps" in violations[0].message

    def test_consistent_state(self):
        """All validators agree and no leftover issues -> OK."""
        validation_result = {"validation_score": 95}
        spec_validation_result = {"is_compliant": True, "suggestions": []}
        refinement_result = {"is_valid": True}

        violations = enforce_validator_state_consistency(
            validation_result, spec_validation_result, refinement_result
        )

        assert len(violations) == 0


class TestFullContractEnforcement:
    """Test the main enforce_story_contracts function."""

    def test_all_contracts_pass(self):
        """Story passes all contracts -> valid."""
        story = {
            "feature_id": 42,
            "title": "Enable PDF upload",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- User can upload\n- System validates",
            "story_points": None,
        }

        result = enforce_story_contracts(
            story=story,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope="Now",
            validation_result={"validation_score": 95},
            spec_validation_result={"is_compliant": True, "suggestions": []},
            refinement_result={"is_valid": True},
            expected_feature_id=42,
        )

        assert result.is_valid
        assert len(result.violations) == 0
        assert result.sanitized_story is not None
    
    def test_invest_score_zero_violation(self):
        """Story with INVEST score of 0 -> violation."""
        story = {
            "feature_id": 42,
            "title": "Enable PDF upload",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- User can upload",
            "story_points": None,
        }

        result = enforce_story_contracts(
            story=story,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame=None,
            allowed_scope=None,
            validation_result={"validation_score": 0},  # Zero score - validation didn't run
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
        )

        assert not result.is_valid
        rules = [v.rule for v in result.violations]
        assert "INVEST_SCORE_ZERO" in rules
    
    def test_feature_id_mismatch_violation(self):
        """Story with wrong feature_id -> violation."""
        story = {
            "feature_id": 101,  # Wrong ID
            "title": "Enable PDF upload",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- User can upload",
            "story_points": None,
        }

        result = enforce_story_contracts(
            story=story,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame=None,
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=82,  # Expected ID
        )

        assert not result.is_valid
        rules = [v.rule for v in result.violations]
        assert "FEATURE_ID_MISMATCH" in rules

    def test_multiple_violations(self):
        """Story violates multiple contracts -> all captured."""
        story = {
            "feature_id": 101,  # Wrong ID
            "title": "Enable PDF upload",
            "description": "As a software engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- User can upload",
            "story_points": 5,  # Forbidden
        }

        result = enforce_story_contracts(
            story=story,
            include_story_points=False,  # Points forbidden
            expected_persona="automation engineer",  # Wrong persona
            feature_time_frame="Next",  # Wrong scope
            allowed_scope="Now",
            validation_result={"validation_score": 0},  # Score zero
            spec_validation_result={"is_compliant": False},  # Spec failed
            refinement_result={"is_valid": True},
            expected_feature_id=82,  # Expected ID different
        )

        assert not result.is_valid
        assert len(result.violations) >= 4  # At least points, persona, invest score, feature ID
        
        # Check specific violations
        rules = [v.rule for v in result.violations]
        assert "STORY_POINTS_FORBIDDEN" in rules
        assert "PERSONA_MISMATCH" in rules
        assert "SCOPE_MISMATCH" in rules
        assert "INVEST_SCORE_ZERO" in rules
        assert "FEATURE_ID_MISMATCH" in rules

    def test_sanitization_strips_forbidden_points(self):
        """Sanitized story has points stripped when forbidden."""
        story = {
            "feature_id": 42,
            "title": "Enable PDF upload",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "story_points": 5,
        }

        result = enforce_story_contracts(
            story=story,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame=None,
            allowed_scope=None,
            validation_result={"validation_score": 85},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
        )

        assert not result.is_valid  # Violation detected
        assert result.sanitized_story["story_points"] is None  # But sanitized


class TestFormatting:
    """Test violation formatting for display."""

    def test_format_single_violation(self):
        """Format single violation for display."""
        story = {"story_points": 5}
        violation = enforce_story_points_contract(story, include_story_points=False)

        formatted = format_contract_violations([violation])

        assert "Contract Violations Detected:" in formatted
        assert "STORY_POINTS_FORBIDDEN" in formatted
        assert "Expected: None" in formatted
        assert "Actual: 5" in formatted

    def test_format_no_violations(self):
        """Format empty violations list."""
        formatted = format_contract_violations([])

        assert formatted == "No contract violations"
