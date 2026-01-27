"""
Tests for story_contract_enforcer.py - deterministic final validation stage.
"""

import pytest
from orchestrator_agent.agent_tools.story_pipeline.story_contract_enforcer import (
    enforce_story_contracts,
    enforce_story_points_contract,
    enforce_persona_contract,
    enforce_scope_contract,
    enforce_feature_id_consistency,
    enforce_validator_state_consistency,
    enforce_theme_epic_contract,
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


class TestFeatureIdConsistency:
    """Test Rule 3: Feature ID consistency."""

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
    """Test Rule 4: Scope contract."""

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
    """Test Rule 5: Validator state consistency."""
    
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
            "theme": "Now – P&ID Ingestion",  # Must match expected
            "epic": "Document Processing",  # Must match expected
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
            theme="Now – P&ID Ingestion",
            epic="Document Processing",
        )

        assert result.is_valid
        assert len(result.violations) == 0
        assert result.sanitized_story is not None
    
    def test_feature_id_mismatch_violation(self):
        """Story with wrong feature_id -> violation."""
        story = {
            "feature_id": 101,  # Wrong ID
            "title": "Enable PDF upload",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- User can upload",
            "story_points": None,
            "theme": "Now – P&ID Ingestion",  # Must match expected
            "epic": "Document Processing",  # Must match expected
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
            theme="Now – P&ID Ingestion",
            epic="Document Processing",
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
            # Note: theme/epic in story don't matter here because source (expected) is invalid
        }

        result = enforce_story_contracts(
            story=story,
            include_story_points=False,  # Points forbidden
            expected_persona="automation engineer",  # Wrong persona
            feature_time_frame="Next",  # Wrong scope
            allowed_scope="Now",
            validation_result={"validation_score": 95},
            spec_validation_result={"is_compliant": False},  # Spec failed
            refinement_result={"is_valid": True},
            expected_feature_id=82,  # Expected ID different
            theme="Unknown",  # Source invalid -> SOURCE_THEME_INVALID
            epic=None,  # Source invalid -> SOURCE_EPIC_INVALID
        )

        assert not result.is_valid
        assert len(result.violations) >= 6  # Now includes theme and epic violations
        
        # Check specific violations
        rules = [v.rule for v in result.violations]
        assert "STORY_POINTS_FORBIDDEN" in rules
        assert "PERSONA_MISMATCH" in rules
        assert "SCOPE_MISMATCH" in rules
        assert "SOURCE_THEME_INVALID" in rules  # Updated: source validation
        assert "SOURCE_EPIC_INVALID" in rules   # Updated: source validation
        assert "FEATURE_ID_MISMATCH" in rules

    def test_sanitization_strips_forbidden_points(self):
        """Sanitized story has points stripped when forbidden."""
        story = {
            "feature_id": 42,
            "title": "Enable PDF upload",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "story_points": 5,
            "theme": "Now – P&ID Ingestion",  # Must match expected
            "epic": "Document Processing",  # Must match expected
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
            theme="Now – P&ID Ingestion",
            epic="Document Processing",
        )

        assert result.sanitized_story["story_points"] is None


class TestThemeEpicContract:
    """Test Rule 4: Theme and Epic metadata contract.
    
    The new signature validates THREE layers:
    1. Source feature metadata (expected_theme, expected_epic) must be valid
    2. Story output must have theme/epic keys attached
    3. Story values must match expected values (no data corruption)
    """

    def test_theme_and_epic_valid_with_matching_story(self):
        """Both theme and epic are valid AND story matches -> no violations."""
        story = {"theme": "Now – P&ID Ingestion", "epic": "Document Processing"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 0

    def test_source_theme_missing(self):
        """Source feature theme is None -> violation (upstream data integrity issue)."""
        story = {"theme": "Now – P&ID Ingestion", "epic": "Document Processing"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme=None,
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "SOURCE_THEME_INVALID"
        assert violations[0].field == "expected_theme"

    def test_source_theme_unknown(self):
        """Source feature theme is 'Unknown' -> violation."""
        story = {"theme": "Unknown", "epic": "Document Processing"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Unknown",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "SOURCE_THEME_INVALID"

    def test_source_epic_missing(self):
        """Source feature epic is None -> violation."""
        story = {"theme": "Now – P&ID Ingestion", "epic": None}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic=None
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "SOURCE_EPIC_INVALID"
        assert violations[0].field == "expected_epic"

    def test_source_epic_unknown(self):
        """Source feature epic is 'Unknown' -> violation."""
        story = {"theme": "Now – P&ID Ingestion", "epic": "Unknown"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Unknown"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "SOURCE_EPIC_INVALID"

    def test_both_source_values_missing(self):
        """Both source theme and epic missing -> two violations."""
        story = {"theme": None, "epic": None}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme=None,
            expected_epic=None
        )
        
        assert len(violations) == 2
        assert violations[0].rule == "SOURCE_THEME_INVALID"
        assert violations[1].rule == "SOURCE_EPIC_INVALID"

    def test_source_theme_empty_string(self):
        """Source theme is empty string -> violation."""
        story = {"theme": "", "epic": "Document Processing"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "SOURCE_THEME_INVALID"

    def test_source_epic_whitespace_only(self):
        """Source epic is whitespace only -> violation."""
        story = {"theme": "Now – P&ID Ingestion", "epic": "   "}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="   "
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "SOURCE_EPIC_INVALID"
    
    def test_story_missing_theme_key(self):
        """Story output doesn't have 'theme' key -> violation (pipeline propagation issue)."""
        story = {"epic": "Document Processing"}  # No theme key
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "STORY_THEME_MISSING"
        assert violations[0].field == "story.theme"

    def test_story_missing_epic_key(self):
        """Story output doesn't have 'epic' key -> violation."""
        story = {"theme": "Now – P&ID Ingestion"}  # No epic key
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "STORY_EPIC_MISSING"
        assert violations[0].field == "story.epic"

    def test_story_theme_is_unknown(self):
        """Story theme is 'Unknown' (even if expected is valid) -> violation."""
        story = {"theme": "Unknown", "epic": "Document Processing"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "STORY_THEME_INVALID"
        assert "roadmap organization" in violations[0].message

    def test_story_epic_is_unknown(self):
        """Story epic is 'Unknown' -> violation."""
        story = {"theme": "Now – P&ID Ingestion", "epic": "Unknown"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "STORY_EPIC_INVALID"
        assert "feature grouping" in violations[0].message

    def test_story_theme_mismatch_detects_data_corruption(self):
        """Story theme doesn't match expected -> MISMATCH violation (data corruption)."""
        story = {"theme": "Wrong Theme", "epic": "Document Processing"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "STORY_THEME_MISMATCH"
        assert "data corruption" in violations[0].message
        assert violations[0].expected == "Now – P&ID Ingestion"
        assert violations[0].actual == "Wrong Theme"

    def test_story_epic_mismatch_detects_data_corruption(self):
        """Story epic doesn't match expected -> MISMATCH violation."""
        story = {"theme": "Now – P&ID Ingestion", "epic": "Wrong Epic"}
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now – P&ID Ingestion",
            expected_epic="Document Processing"
        )
        
        assert len(violations) == 1
        assert violations[0].rule == "STORY_EPIC_MISMATCH"
        assert violations[0].expected == "Document Processing"
        assert violations[0].actual == "Wrong Epic"


class TestIntegrationWithThemeEpic:
    """Test integration of theme/epic enforcement in enforce_story_contracts.
    
    These tests verify the FULL contract enforcement pipeline where:
    1. Story dict must have theme/epic keys attached
    2. Story values must match expected_theme/expected_epic from source feature
    """

    def test_full_contract_with_valid_theme_epic(self):
        """Full contract with valid theme/epic -> passes."""
        story = {
            "title": "Upload P&ID",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload PDF\n- Shows preview",
            "story_points": 3,
            "feature_id": 42,
            "theme": "Now – P&ID Ingestion",  # Must match expected
            "epic": "Document Processing",  # Must match expected
        }
        
        result = enforce_story_contracts(
            story=story,
            include_story_points=True,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",
            epic="Document Processing",
        )
        
        assert result.is_valid is True
        assert len(result.violations) == 0

    def test_full_contract_with_missing_source_theme(self):
        """Full contract with missing source theme -> fails (SOURCE_THEME_INVALID)."""
        story = {
            "title": "Upload P&ID",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload PDF\n- Shows preview",
            "story_points": 3,
            "feature_id": 42,
            "theme": "Unknown",  # Story has this because source was invalid
            "epic": "Document Processing",
        }
        
        result = enforce_story_contracts(
            story=story,
            include_story_points=True,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Unknown",  # Source feature has invalid theme
            epic="Document Processing",
        )
        
        assert result.is_valid is False
        assert any(v.rule == "SOURCE_THEME_INVALID" for v in result.violations)

    def test_full_contract_with_story_missing_theme_key(self):
        """Story dict doesn't have theme key attached -> fails (STORY_THEME_MISSING)."""
        story = {
            "title": "Upload P&ID",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload PDF\n- Shows preview",
            "story_points": 3,
            "feature_id": 42,
            # No theme key! Pipeline didn't propagate metadata
            "epic": "Document Processing",
        }
        
        result = enforce_story_contracts(
            story=story,
            include_story_points=True,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",  # Valid source
            epic="Document Processing",
        )
        
        assert result.is_valid is False
        assert any(v.rule == "STORY_THEME_MISSING" for v in result.violations)

    def test_full_contract_with_story_theme_mismatch(self):
        """Story theme doesn't match source feature -> fails (STORY_THEME_MISMATCH)."""
        story = {
            "title": "Upload P&ID",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload PDF\n- Shows preview",
            "story_points": 3,
            "feature_id": 42,
            "theme": "Wrong Theme",  # Data corruption!
            "epic": "Document Processing",
        }
        
        result = enforce_story_contracts(
            story=story,
            include_story_points=True,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",  # Expected
            epic="Document Processing",
        )
        
        assert result.is_valid is False
        assert any(v.rule == "STORY_THEME_MISMATCH" for v in result.violations)


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


class TestRegressionThemeEpicLoss:
    """
    Regression tests for the "Theme: Unknown | Epic: Unknown" bug.
    
    These tests simulate the failure modes that could cause theme/epic metadata
    to be lost during the story pipeline, ensuring the contract enforcer catches them.
    
    Known failure modes:
    1. Story dict replaced instead of merged after LLM refinement (loses attached metadata)
    2. Feature payload built from different query/DTO that drops theme/epic
    3. "Unknown" injected as default somewhere in serialization chain
    4. Metadata not attached before contract enforcement
    """

    def test_regression_story_dict_replaced_loses_metadata(self):
        """
        Regression: If LLM refinement REPLACES the story dict instead of MERGING,
        theme/epic are lost. Contract should catch STORY_THEME_MISSING.
        """
        # Simulate: LLM refinement returns a new story dict without theme/epic
        refined_story_from_llm = {
            "title": "Upload P&ID documents",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload\n- Shows feedback",
            "story_points": None,
            "feature_id": 42,
            # NOTE: No theme/epic keys - simulates replacement bug
        }
        
        result = enforce_story_contracts(
            story=refined_story_from_llm,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",  # Valid source
            epic="Document Processing",    # Valid source
        )
        
        assert result.is_valid is False, "Contract should reject story missing theme/epic"
        rules = [v.rule for v in result.violations]
        assert "STORY_THEME_MISSING" in rules
        assert "STORY_EPIC_MISSING" in rules

    def test_regression_unknown_injected_as_default(self):
        """
        Regression: If "Unknown" is injected as a default somewhere in the pipeline,
        contract should reject it as invalid metadata.
        """
        # Simulate: Some serializer or Pydantic default sets "Unknown"
        story_with_unknown = {
            "title": "Upload P&ID documents",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload",
            "story_points": None,
            "feature_id": 42,
            "theme": "Unknown",  # Bad default injected
            "epic": "Unknown",   # Bad default injected
        }
        
        result = enforce_story_contracts(
            story=story_with_unknown,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",  # Valid source
            epic="Document Processing",    # Valid source
        )
        
        assert result.is_valid is False, "Contract should reject 'Unknown' as invalid"
        rules = [v.rule for v in result.violations]
        assert "STORY_THEME_INVALID" in rules
        assert "STORY_EPIC_INVALID" in rules

    def test_regression_source_feature_has_bad_metadata(self):
        """
        Regression: If the source feature itself has bad metadata (upstream bug),
        contract should fail fast with SOURCE_*_INVALID before checking story.
        """
        # Simulate: Feature query returned "Unknown" or None for theme/epic
        story = {
            "title": "Upload P&ID documents",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload",
            "story_points": None,
            "feature_id": 42,
            "theme": "Unknown",  # Propagated from bad source
            "epic": None,        # Propagated from bad source
        }
        
        result = enforce_story_contracts(
            story=story,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Unknown",  # Source itself is invalid
            epic=None,        # Source itself is invalid
        )
        
        assert result.is_valid is False
        rules = [v.rule for v in result.violations]
        # Source validation fails FIRST, so we get SOURCE_* violations
        assert "SOURCE_THEME_INVALID" in rules
        assert "SOURCE_EPIC_INVALID" in rules

    def test_regression_metadata_mismatch_detects_corruption(self):
        """
        Regression: If story's theme/epic don't match source feature (data corruption),
        contract should detect the mismatch.
        """
        # Simulate: Story got attached to wrong feature's metadata somehow
        story_with_wrong_metadata = {
            "title": "Upload P&ID documents",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload",
            "story_points": None,
            "feature_id": 42,
            "theme": "Next – Advanced Analytics",  # Wrong theme!
            "epic": "Data Visualization",          # Wrong epic!
        }
        
        result = enforce_story_contracts(
            story=story_with_wrong_metadata,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",  # Expected from source
            epic="Document Processing",    # Expected from source
        )
        
        assert result.is_valid is False
        rules = [v.rule for v in result.violations]
        assert "STORY_THEME_MISMATCH" in rules
        assert "STORY_EPIC_MISMATCH" in rules
        
        # Verify violation includes diagnostic info
        theme_violation = next(v for v in result.violations if v.rule == "STORY_THEME_MISMATCH")
        assert theme_violation.expected == "Now – P&ID Ingestion"
        assert theme_violation.actual == "Next – Advanced Analytics"

    def test_regression_empty_string_metadata_rejected(self):
        """
        Regression: Empty string theme/epic should be rejected (not just None/Unknown).
        """
        story_with_empty = {
            "title": "Upload P&ID documents",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload",
            "story_points": None,
            "feature_id": 42,
            "theme": "",   # Empty string
            "epic": "  ",  # Whitespace only
        }
        
        result = enforce_story_contracts(
            story=story_with_empty,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",
            epic="Document Processing",
        )
        
        assert result.is_valid is False
        rules = [v.rule for v in result.violations]
        assert "STORY_THEME_INVALID" in rules
        assert "STORY_EPIC_INVALID" in rules

    def test_regression_valid_path_with_metadata_preserved(self):
        """
        Positive test: When metadata is properly propagated, all contracts pass.
        This is the "golden path" that should always work.
        """
        story_with_metadata = {
            "title": "Upload P&ID documents",
            "description": "As an automation engineer, I want to upload PDFs so that I can process them.",
            "acceptance_criteria": "- Can upload\n- Shows feedback",
            "story_points": None,
            "feature_id": 42,
            "theme": "Now – P&ID Ingestion",    # Correctly propagated
            "epic": "Document Processing",       # Correctly propagated
        }
        
        result = enforce_story_contracts(
            story=story_with_metadata,
            include_story_points=False,
            expected_persona="automation engineer",
            feature_time_frame="Now",
            allowed_scope=None,
            validation_result={"validation_score": 95},
            spec_validation_result=None,
            refinement_result={"is_valid": True},
            expected_feature_id=42,
            theme="Now – P&ID Ingestion",
            epic="Document Processing",
        )
        
        assert result.is_valid is True
        assert len(result.violations) == 0
