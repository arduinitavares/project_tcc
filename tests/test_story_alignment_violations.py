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

from orchestrator_agent.agent_tools.story_pipeline.alignment_checker import (
    AlignmentResult,
    check_alignment_violation,
    create_rejection_response,
    detect_requirement_drift,
    extract_forbidden_capabilities,
    validate_feature_alignment,
)


# =============================================================================
# Unit Tests for alignment_checker module (deterministic, no LLM)
# =============================================================================


class TestExtractForbiddenCapabilities:
    """Tests for extract_forbidden_capabilities function."""

    def test_mobile_only_vision_forbids_web(self):
        """Mobile-only vision should forbid web/desktop capabilities."""
        vision = "Tennis Tracker is a mobile-only app that helps record scores and stats."
        forbidden = extract_forbidden_capabilities(vision)
        
        assert "web" in forbidden
        assert "desktop" in forbidden
        assert "browser" in forbidden

    def test_offline_first_vision_forbids_realtime(self):
        """Offline-first vision should forbid real-time sync capabilities."""
        vision = (
            "Workout Logger is an offline-first mobile app that stores workouts locally. "
            "Unlike cloud-based trackers, our product works without internet access."
        )
        forbidden = extract_forbidden_capabilities(vision)
        
        assert "real-time" in forbidden
        assert "cloud sync" in forbidden
        assert "server sync" in forbidden

    def test_distraction_free_vision_forbids_notifications(self):
        """Distraction-free vision should forbid notification capabilities."""
        vision = (
            "Reading Journal is a simple note-taking app for tracking books. "
            "Unlike social reading platforms, our product is private and distraction-free."
        )
        forbidden = extract_forbidden_capabilities(vision)
        
        assert "notifications" in forbidden
        assert "alerts" in forbidden
        assert "push" in forbidden
        assert "reminders" in forbidden

    def test_casual_home_use_vision_forbids_industrial(self):
        """Casual home-use vision should forbid industrial capabilities."""
        vision = (
            "Home Garden Planner is a simple mobile app for tracking plants. "
            "Unlike professional agriculture software, our product is designed for casual home use."
        )
        forbidden = extract_forbidden_capabilities(vision)
        
        assert "industrial" in forbidden
        assert "plc" in forbidden
        assert "opc ua" in forbidden

    def test_empty_vision_returns_empty_list(self):
        """Empty or None vision should return no forbidden capabilities."""
        assert extract_forbidden_capabilities(None) == []
        assert extract_forbidden_capabilities("") == []

    def test_generic_vision_returns_empty_list(self):
        """Vision without constraint keywords returns no forbidden capabilities."""
        vision = "Our app helps users manage their tasks efficiently."
        forbidden = extract_forbidden_capabilities(vision)
        assert forbidden == []


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
        """Web-based dashboard should fail for mobile-only vision."""
        result = validate_feature_alignment(
            feature_title="Web-based analytics dashboard",
            product_vision=(
                "Tennis Tracker is a mobile-only app that helps record scores. "
                "Unlike complex desktop software, our product focuses on quick mobile data entry."
            )
        )
        
        assert not result.is_aligned
        assert len(result.alignment_issues) >= 1
        assert any("web" in issue.lower() for issue in result.alignment_issues)

    def test_realtime_fails_for_offline_first_vision(self):
        """Real-time sync should fail for offline-first vision."""
        result = validate_feature_alignment(
            feature_title="Real-time workout synchronization with cloud",
            product_vision=(
                "For fitness enthusiasts who train in areas with poor connectivity, "
                "Workout Logger is an offline-first mobile app that stores workouts locally. "
                "Unlike cloud-based trackers, our product works without internet access."
            )
        )
        
        assert not result.is_aligned
        assert any("real-time" in issue.lower() for issue in result.alignment_issues)

    def test_notifications_fail_for_distraction_free_vision(self):
        """Push notifications should fail for distraction-free vision."""
        result = validate_feature_alignment(
            feature_title="Push notifications and reading reminders",
            product_vision=(
                "Reading Journal is a simple note-taking app for tracking books and quotes. "
                "Unlike social reading platforms, our product is private and distraction-free."
            )
        )
        
        assert not result.is_aligned
        # Should catch notifications, push, AND reminders
        assert len(result.forbidden_found) >= 2

    def test_industrial_fails_for_consumer_vision(self):
        """Industrial PLC integration should fail for casual home-use vision."""
        result = validate_feature_alignment(
            feature_title="Integration with industrial PLC controllers and OPC UA sensors",
            product_vision=(
                "Home Garden Planner is a simple mobile app for tracking plants and harvest dates. "
                "Unlike professional agriculture software, our product is designed for casual home use."
            )
        )
        
        assert not result.is_aligned
        assert any("industrial" in issue.lower() or "plc" in issue.lower() 
                   for issue in result.alignment_issues)

    def test_aligned_feature_passes(self):
        """Feature that aligns with vision should pass."""
        result = validate_feature_alignment(
            feature_title="View match history and statistics",
            product_vision=(
                "Tennis Tracker is a mobile-only app that helps record scores. "
                "Unlike complex desktop software, our product focuses on quick mobile data entry."
            )
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
            product_vision="Mobile-only app for tracking tennis scores"
        )
        
        assert response["success"] is False
        assert response["is_valid"] is False
        assert response["rejected"] is True
        assert "alignment_issues" in response
        assert len(response["alignment_issues"]) >= 1
        assert "[REJECTED]" in response["story"]["title"]
        assert response["validation_score"] == 0

    def test_includes_vision_excerpt(self):
        """Should include vision excerpt for context."""
        long_vision = "A" * 300  # Long vision statement
        response = create_rejection_response(
            feature_title="Test feature",
            alignment_issues=["Test issue"],
            product_vision=long_vision
        )
        
        # Should be truncated with ...
        assert response["product_vision_excerpt"].endswith("...")
        assert len(response["product_vision_excerpt"]) < len(long_vision)


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
            "Tennis Tracker is a mobile-only app"
        )
        
        assert not feature_alignment.is_aligned
        
        # This is what process_single_story would return
        rejection = create_rejection_response(
            feature_title="Web-based analytics dashboard",
            alignment_issues=feature_alignment.alignment_issues,
            product_vision="Tennis Tracker is a mobile-only app"
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
        forbidden = extract_forbidden_capabilities(
            "Workout Logger is an offline-first app that works without internet"
        )
        
        drift, message = detect_requirement_drift(
            original_feature=original,
            final_story_title=final_title,
            final_story_description=final_desc,
            forbidden_capabilities=forbidden
        )
        
        assert drift is True
        assert "drift" in message.lower()

    def test_combined_vision_constraints(self):
        """
        Test vision with multiple constraint types.
        
        A vision can have multiple constraints (e.g., mobile-only AND offline-first).
        """
        vision = (
            "QuickNotes is a mobile-only, offline-first app for simple note-taking. "
            "It's designed for distraction-free writing without internet requirements."
        )
        
        forbidden = extract_forbidden_capabilities(vision)
        
        # Should have constraints from multiple patterns
        assert "web" in forbidden  # mobile-only
        assert "real-time" in forbidden  # offline-first
        assert "notifications" in forbidden  # distraction-free
        
        # Test various violations
        web_feature = validate_feature_alignment("Browser extension", vision)
        assert not web_feature.is_aligned
        
        sync_feature = validate_feature_alignment("Real-time cloud backup", vision)
        assert not sync_feature.is_aligned
        
        notif_feature = validate_feature_alignment("Push notification alerts", vision)
        assert not notif_feature.is_aligned
        
        # Aligned feature should pass
        aligned = validate_feature_alignment("Quick note entry screen", vision)
        assert aligned.is_aligned
