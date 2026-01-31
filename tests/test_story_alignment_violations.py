# tests/test_story_alignment_violations.py
"""
Tests for story pipeline alignment validation.

These tests verify that the pipeline correctly rejects user stories
that violate product vision constraints, and does NOT silently
transform out-of-scope features into different features.

Test cases from STORY_ALIGNMENT_VALIDATION_ISSUE.md:
1. Dashboard story fails for mobile-only vision
2. Real-time sync fails for offline-first vision
3. Notifications fail for distraction-free vision
4. PLC/industrial fails for casual home-use vision
5. Aligned stories pass normally (control test)
"""

import pytest

from agile_sqlmodel import CompiledSpecAuthority
from utils.schemes import (
    ForbiddenCapabilityParams,
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SourceMapEntry,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)

from orchestrator_agent.agent_tools.story_pipeline.alignment_checker import (
    AlignmentResult,
    check_alignment_violation,
    create_rejection_response,
    detect_requirement_drift,
    derive_forbidden_capabilities_from_invariants,
    derive_forbidden_capabilities_from_authority,
    validate_feature_alignment,
)


def _make_compiled_authority_with_invariants() -> CompiledSpecAuthority:
    invariants = [
        Invariant(
            id="INV-0000000000000000",
            type=InvariantType.REQUIRED_FIELD,
            parameters=RequiredFieldParams(field_name="user_id"),
        ),
        Invariant(
            id="INV-1111111111111111",
            type=InvariantType.FORBIDDEN_CAPABILITY,
            parameters=ForbiddenCapabilityParams(capability="OAuth1"),
        ),
    ]
    success = SpecAuthorityCompilationSuccess(
        scope_themes=["core"],
        invariants=invariants,
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[
            SourceMapEntry(
                invariant_id="INV-0000000000000000",
                excerpt="The payload must include user_id.",
            ),
            SourceMapEntry(
                invariant_id="INV-1111111111111111",
                excerpt="The system must not use OAuth1.",
            ),
        ],
        compiler_version="1.0.0",
        prompt_hash="0" * 64,
    )
    return CompiledSpecAuthority(
        spec_version_id=1,
        compiler_version="1.0.0",
        prompt_hash="test",
        scope_themes="[]",
        invariants="[]",
        eligible_feature_ids="[]",
        rejected_features="[]",
        spec_gaps="[]",
        compiled_artifact_json=SpecAuthorityCompilerOutput(root=success).model_dump_json(),
    )


# =============================================================================
# Unit Tests for alignment_checker module (deterministic, no LLM)
# =============================================================================


class TestDeriveForbiddenCapabilities:
    """Tests for derive_forbidden_capabilities_from_invariants function."""

    def test_derives_only_forbidden_capabilities(self):
        """Only FORBIDDEN_CAPABILITY invariants should be used."""
        invariants = [
            "FORBIDDEN_CAPABILITY:web",
            "REQUIRED_FIELD:user_id",
            "MAX_VALUE:count<=10",
        ]
        forbidden = derive_forbidden_capabilities_from_invariants(invariants)

        assert [item.term for item in forbidden] == ["web"]

    def test_empty_invariants_return_empty_list(self):
        """Empty invariants should return no forbidden capabilities."""
        assert derive_forbidden_capabilities_from_invariants([]) == []


class TestForbiddenCapabilitiesFromAuthority:
    """Tests for compiled_artifact_json forbidden derivation."""

    def test_structured_forbidden_excludes_required(self):
        """Structured invariants should return only FORBIDDEN_CAPABILITY terms."""
        compiled_authority = _make_compiled_authority_with_invariants()

        forbidden = derive_forbidden_capabilities_from_authority(compiled_authority)
        assert [item.term for item in forbidden] == ["oauth1"]

    def test_alignment_ignores_required_fields(self):
        """Features with user_id should not be rejected; OAuth1 should be rejected."""
        compiled_authority = _make_compiled_authority_with_invariants()

        allowed = validate_feature_alignment(
            feature_title="Capture user_id in payload",
            compiled_authority=compiled_authority,
        )
        assert allowed.is_aligned

        blocked = validate_feature_alignment(
            feature_title="OAuth1 login flow",
            compiled_authority=compiled_authority,
        )
        assert not blocked.is_aligned
        assert any("oauth1" in issue.lower() for issue in blocked.alignment_issues)


class TestCheckAlignmentViolation:
    """Tests for check_alignment_violation function."""

    def test_detects_web_in_feature(self):
        """Should detect 'web' in feature title."""
        result = check_alignment_violation(
            text="Web-based analytics dashboard",
            forbidden_capabilities=["web", "desktop"],
            context_label="feature"
        )
        
        assert not result.is_aligned
        assert len(result.alignment_issues) >= 1
        assert "web" in result.forbidden_found

    def test_detects_realtime_in_description(self):
        """Should detect 'real-time' in story description."""
        result = check_alignment_violation(
            text="As a user, I want real-time synchronization with the cloud",
            forbidden_capabilities=["real-time", "cloud sync"],
            context_label="story"
        )
        
        assert not result.is_aligned
        assert "real-time" in result.forbidden_found

    def test_detects_notifications(self):
        """Should detect 'notifications' as forbidden capability."""
        result = check_alignment_violation(
            text="Push notifications and reading reminders",
            forbidden_capabilities=["notifications", "push", "reminders"],
            context_label="feature"
        )
        
        assert not result.is_aligned
        assert len(result.forbidden_found) >= 2  # Should catch multiple

    def test_detects_industrial_terms(self):
        """Should detect industrial/PLC terms."""
        result = check_alignment_violation(
            text="Integration with industrial PLC controllers and OPC UA sensors",
            forbidden_capabilities=["industrial", "plc", "opc ua"],
            context_label="feature"
        )
        
        assert not result.is_aligned
        assert "industrial" in result.forbidden_found
        assert "plc" in result.forbidden_found

    def test_aligned_text_passes(self):
        """Text without forbidden terms should pass."""
        result = check_alignment_violation(
            text="View match history and statistics",
            forbidden_capabilities=["web", "desktop", "real-time"],
            context_label="feature"
        )
        
        assert result.is_aligned
        assert result.alignment_issues == []
        assert result.forbidden_found == []

    def test_word_boundary_matching(self):
        """Should use word boundaries to avoid false positives."""
        # "cobweb" contains "web" but shouldn't match
        result = check_alignment_violation(
            text="Remove cobweb from the garden",
            forbidden_capabilities=["web"],
            context_label="feature"
        )
        
        # This should NOT trigger because "web" is part of "cobweb"
        assert result.is_aligned


class TestDetectRequirementDrift:
    """Tests for detect_requirement_drift function."""

    def test_detects_web_to_mobile_drift(self):
        """Should detect when web feature was transformed to mobile."""
        drift, message = detect_requirement_drift(
            original_feature="Web-based analytics dashboard",
            final_story_title="Mobile analytics screen",
            final_story_description="As a user, I want to view analytics on my mobile device",
            forbidden_capabilities=["web", "desktop", "browser"]
        )
        
        assert drift is True
        assert message is not None
        assert "drift" in message.lower()
        assert "web" in message.lower()

    def test_detects_realtime_to_manual_drift(self):
        """Should detect when real-time was transformed to manual."""
        drift, message = detect_requirement_drift(
            original_feature="Real-time cloud sync feature",
            final_story_title="Manual data backup",
            final_story_description="As a user, I want to manually backup my data",
            forbidden_capabilities=["real-time", "cloud sync", "live"]
        )
        
        assert drift is True
        assert message is not None

    def test_no_drift_when_original_is_aligned(self):
        """Should not detect drift when original feature was already aligned."""
        drift, message = detect_requirement_drift(
            original_feature="View match history",  # No forbidden terms
            final_story_title="Browse match records",
            final_story_description="As a user, I want to view my past matches",
            forbidden_capabilities=["web", "desktop"]
        )
        
        assert drift is False
        assert message is None

    def test_no_drift_when_forbidden_terms_remain(self):
        """Should not detect drift if forbidden terms are still in final story."""
        # This case shouldn't happen (would be caught by alignment check)
        # but tests the logic
        drift, message = detect_requirement_drift(
            original_feature="Web-based dashboard",
            final_story_title="Web analytics panel",  # Still has 'web'
            final_story_description="As a user, I want a web interface",
            forbidden_capabilities=["web"]
        )
        
        assert drift is False


class TestValidateFeatureAlignment:
    """Tests for validate_feature_alignment function (end-to-end check)."""

    def test_dashboard_fails_for_mobile_only_vision(self):
        """Web-based dashboard should fail for mobile-only invariants."""
        result = validate_feature_alignment(
            feature_title="Web-based analytics dashboard",
            _invariants=[
                "FORBIDDEN_CAPABILITY:web",
                "FORBIDDEN_CAPABILITY:desktop",
            ],
        )
        
        assert not result.is_aligned
        assert len(result.alignment_issues) >= 1
        assert any("web" in issue.lower() for issue in result.alignment_issues)

    def test_realtime_fails_for_offline_first_vision(self):
        """Real-time sync should fail for offline-first invariants."""
        result = validate_feature_alignment(
            feature_title="Real-time workout synchronization with cloud",
            _invariants=[
                "FORBIDDEN_CAPABILITY:real-time",
                "FORBIDDEN_CAPABILITY:cloud sync",
            ],
        )
        
        assert not result.is_aligned
        assert any("real-time" in issue.lower() for issue in result.alignment_issues)

    def test_notifications_fail_for_distraction_free_vision(self):
        """Push notifications should fail for distraction-free invariants."""
        result = validate_feature_alignment(
            feature_title="Push notifications and reading reminders",
            _invariants=[
                "FORBIDDEN_CAPABILITY:notifications",
                "FORBIDDEN_CAPABILITY:reminders",
                "FORBIDDEN_CAPABILITY:push",
            ],
        )
        
        assert not result.is_aligned
        # Should catch notifications, push, AND reminders
        assert len(result.forbidden_found) >= 2

    def test_industrial_fails_for_consumer_vision(self):
        """Industrial PLC integration should fail for consumer invariants."""
        result = validate_feature_alignment(
            feature_title="Integration with industrial PLC controllers and OPC UA sensors",
            _invariants=[
                "FORBIDDEN_CAPABILITY:industrial",
                "FORBIDDEN_CAPABILITY:plc",
                "FORBIDDEN_CAPABILITY:opc ua",
            ],
        )
        
        assert not result.is_aligned
        assert any("industrial" in issue.lower() or "plc" in issue.lower() 
                   for issue in result.alignment_issues)

    def test_aligned_feature_passes(self):
        """Feature that aligns with vision should pass."""
        result = validate_feature_alignment(
            feature_title="View match history and statistics",
            _invariants=["FORBIDDEN_CAPABILITY:desktop"]
        )
        
        assert result.is_aligned
        assert result.alignment_issues == []


class TestCreateRejectionResponse:
    """Tests for create_rejection_response function."""

    def test_creates_proper_rejection_structure(self):
        """Should create a properly structured rejection response."""
        response = create_rejection_response(
            feature_title="Web-based dashboard",
            alignment_issues=["Feature violates vision: contains 'web'"],
            invariants=["mobile-only app", "no web"]
        )
        
        assert response["success"] is False
        assert response["is_valid"] is False
        assert response["rejected"] is True
        assert "alignment_issues" in response
        assert len(response["alignment_issues"]) >= 1
        assert "[REJECTED]" in response["story"]["title"]
        assert response["validation_score"] == 0

    def test_includes_invariants_excerpt(self):
        """Should include invariants excerpt for context."""
        long_invariants = ["A" * 300]
        response = create_rejection_response(
            feature_title="Test feature",
            alignment_issues=["Test issue"],
            invariants=long_invariants
        )
        
        # Should be truncated with ...
        assert response["invariants_excerpt"].endswith("...")
        assert len(response["invariants_excerpt"]) < len(long_invariants[0])


# =============================================================================
# Integration Tests (may require mocking or be marked as slow)
# =============================================================================


class TestAlignmentEnforcementIntegration:
    """
    Integration tests that verify the full alignment enforcement flow.
    
    These tests check that:
    1. Fail-fast rejection works for obviously misaligned features
    2. Post-pipeline veto catches stories that slipped through
    3. Drift detection catches silent transformations
    """

    def test_fail_fast_rejection_structure(self):
        """
        Test that fail-fast rejection produces the expected response structure.
        
        This simulates what process_single_story returns when a feature
        is rejected during the initial alignment check.
        """
        # Simulate the fail-fast path
        feature_alignment = validate_feature_alignment(
            "Web-based analytics dashboard",
            _invariants=["FORBIDDEN_CAPABILITY:web"]
        )
        
        assert not feature_alignment.is_aligned
        
        # This is what process_single_story would return
        rejection = create_rejection_response(
            feature_title="Web-based analytics dashboard",
            alignment_issues=feature_alignment.alignment_issues,
            invariants=["FORBIDDEN_CAPABILITY:web"]
        )
        
        # Verify rejection has required fields
        assert "success" in rejection
        assert "is_valid" in rejection
        assert "rejected" in rejection
        assert "alignment_issues" in rejection
        assert rejection["is_valid"] is False
        assert rejection["rejected"] is True

    def test_drift_detection_catches_transformation(self):
        """
        Test that drift detection catches when a story was silently transformed.
        
        This simulates the post-pipeline check where the original feature
        had forbidden terms but the final story doesn't.
        """
        # Original feature has "real-time" which is forbidden
        original = "Real-time workout synchronization"
        
        # Final story was transformed to remove the forbidden term
        final_title = "Manual workout backup"
        final_desc = "As a user, I want to manually save my workout data"
        
        # Vision forbids real-time
        forbidden = derive_forbidden_capabilities_from_invariants(
            ["FORBIDDEN_CAPABILITY:real-time", "FORBIDDEN_CAPABILITY:cloud sync"]
        )
        forbidden_terms = [item.term for item in forbidden]
        
        drift, message = detect_requirement_drift(
            original_feature=original,
            final_story_title=final_title,
            final_story_description=final_desc,
            forbidden_capabilities=forbidden_terms
        )
        
        assert drift is True
        assert "drift" in message.lower()

    def test_combined_vision_constraints(self):
        """
        Test vision with multiple constraint types.
        
        A vision can have multiple constraints (e.g., mobile-only AND offline-first).
        """
        invariants = [
            "FORBIDDEN_CAPABILITY:web",
            "FORBIDDEN_CAPABILITY:real-time",
            "FORBIDDEN_CAPABILITY:notifications",
        ]

        forbidden = derive_forbidden_capabilities_from_invariants(invariants)
        forbidden_terms = [item.term for item in forbidden]
        
        # Should have constraints from multiple patterns
        assert "web" in forbidden_terms
        assert "real-time" in forbidden_terms
        assert "notifications" in forbidden_terms
        
        # Test various violations
        web_feature = validate_feature_alignment("Web browser extension", _invariants=invariants)
        assert not web_feature.is_aligned
        
        sync_feature = validate_feature_alignment("Real-time cloud backup", _invariants=invariants)
        assert not sync_feature.is_aligned
        
        notif_feature = validate_feature_alignment("Push notifications alerts", _invariants=invariants)
        assert not notif_feature.is_aligned
        
        # Aligned feature should pass
        aligned = validate_feature_alignment("Quick note entry screen", _invariants=invariants)
        assert aligned.is_aligned
