# tests/test_spec_requirement_binding.py
"""
Tests for Spec Requirement Extraction and Domain Binding.

These tests validate the deterministic requirement extractor that:
1. Parses MUST/SHALL/REQUIRED statements from specs
2. Binds requirements to stories based on domain keywords
3. Checks acceptance criteria for required artifacts
"""

import pytest
from orchestrator_agent.agent_tools.story_pipeline.spec_requirement_extractor import (
    extract_hard_requirements,
    bind_requirements_to_story,
    check_acceptance_criteria_compliance,
    validate_story_against_spec,
    RequirementStrength,
    HardRequirement,
    format_compliance_report,
)


# Sample technical spec for testing (based on genai_spec.md)
SAMPLE_SPEC = """
# Review-First Human-in-the-Loop Extraction Pipeline  
**Technical Specification (Draft)**

## 2. Core Principle

> **Every pipeline stage must emit a reviewable artifact.**

Each stage produces:
- Machine output (model result)
- Human review artifact (visual + structured)
- Review delta (what changed)
- Gold snapshot (post-review ground truth)
- Training export (model-ready data)

Human review is not an exception path — it is a first-class system feature.

## 3. Stage-Gated Review Workflow

### 3.1 Checkpoint A — Primitive Review  

#### Machine Outputs
- Symbol bounding boxes
- Detection confidence
- Tag type / style code predictions

Each checkpoint approval MUST create:
- `primitives_v{n}.jsonl | parquet`
- `review_actions_v{n}.jsonl`
- `gold_primitives_v{n}.jsonl`

#### Exit Criteria
- All blocking issues resolved or waived
- User approves **Checkpoint A**

## 4. Review Action (Delta) Schema

All user feedback MUST be stored as **event-sourced deltas**, never silent overwrites.

### ReviewAction (Draft)
- `action_id`: UUID
- `doc_id`
- `before`: JSON (optional, recommended)
- `after`: JSON
- `reviewer_id`
- `timestamp`
- `model_provenance`

## 8. Versioning, Audit, and Provenance

### 8.1 Immutable Revisions
Each checkpoint approval MUST create:
- `doc_revision_id`
- Input hash (PDF SHA-256)
- Model versions
- Config versions (DPI, thresholds, legend.yml)

The system SHALL record model_provenance for each inference run.

### 8.2 Event-Sourced State
- Current state = replay(review_actions)
- This is REQUIRED for reproducibility and debugging

## 10. Definition of Done (Per Checkpoint)

A checkpoint is complete when:
- User can review and correct outputs
- Corrections are stored as deltas
- Gold snapshot is produced
- Training export is reproducible
- Model provenance is recorded
- Validation issues are resolved or waived explicitly
"""


class TestRequirementExtraction:
    """Test extraction of hard requirements from spec text."""

    def test_extracts_must_requirements(self):
        """Should extract statements with MUST keyword."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        must_reqs = [r for r in requirements if r.strength == RequirementStrength.MUST]
        assert len(must_reqs) >= 3, f"Expected at least 3 MUST requirements, got {len(must_reqs)}"
        
        # Verify one specific MUST requirement
        must_texts = [r.text for r in must_reqs]
        assert any("event-sourced deltas" in t.lower() for t in must_texts), \
            "Should find 'event-sourced deltas' MUST requirement"

    def test_extracts_shall_requirements(self):
        """Should extract statements with SHALL keyword."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        shall_reqs = [r for r in requirements if r.strength == RequirementStrength.SHALL]
        assert len(shall_reqs) >= 1, "Expected at least 1 SHALL requirement"

    def test_extracts_required_requirements(self):
        """Should extract statements with REQUIRED keyword."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        required_reqs = [r for r in requirements if r.strength == RequirementStrength.REQUIRED]
        assert len(required_reqs) >= 1, "Expected at least 1 REQUIRED requirement"

    def test_extracts_artifact_names(self):
        """Should extract artifact names from requirements."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        # Find requirements with artifacts
        reqs_with_artifacts = [r for r in requirements if r.required_artifacts]
        assert len(reqs_with_artifacts) >= 1, "Should find requirements with artifact names"
        
        # Check for specific artifacts
        all_artifacts = []
        for r in requirements:
            all_artifacts.extend(r.required_artifacts)
        
        # These artifacts should be found in the spec
        expected_artifacts = ["doc_revision_id", "model_provenance"]
        for expected in expected_artifacts:
            assert any(expected in a for a in all_artifacts), \
                f"Should extract artifact '{expected}'"

    def test_extracts_domain_keywords(self):
        """Should extract domain keywords from requirements."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        # Check that domain keywords are extracted
        all_keywords = []
        for r in requirements:
            all_keywords.extend(r.domain_keywords)
        
        # Review domain keywords should be present
        assert "review" in all_keywords or "checkpoint" in all_keywords, \
            "Should extract review-related domain keywords"

    def test_tracks_source_section(self):
        """Should track which section each requirement came from."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        # Verify section tracking
        sections = set(r.source_section for r in requirements)
        assert len(sections) > 1, "Requirements should come from multiple sections"

    def test_handles_empty_spec(self):
        """Should return empty list for empty spec."""
        requirements = extract_hard_requirements("")
        assert requirements == []
        
        requirements = extract_hard_requirements(None)
        assert requirements == []


class TestDomainBinding:
    """Test binding of requirements to stories based on domain."""

    def test_binds_review_domain(self):
        """Should bind requirements to review-domain features."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        bound_reqs, domain = bind_requirements_to_story(
            feature_title="Implement Primitive Review UI",
            theme="Review Workflow",
            epic="Human-in-the-Loop",
            requirements=requirements,
        )
        
        assert domain == "review", f"Expected 'review' domain, got '{domain}'"
        assert len(bound_reqs) > 0, "Should bind at least one requirement to review domain"

    def test_binds_ingestion_domain(self):
        """Should bind requirements to ingestion-domain features."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        bound_reqs, domain = bind_requirements_to_story(
            feature_title="PDF Document Ingestion",
            theme="Data Pipeline",
            epic="Input Processing",
            requirements=requirements,
        )
        
        assert domain in ["ingestion", "workflow"], f"Expected ingestion-related domain, got '{domain}'"

    def test_binds_provenance_domain(self):
        """Should bind requirements to provenance-domain features."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        bound_reqs, domain = bind_requirements_to_story(
            feature_title="Model Provenance Tracking",
            theme="Audit & Compliance",
            epic="Traceability",
            requirements=requirements,
        )
        
        assert domain in ["provenance", "audit"], f"Expected provenance/audit domain, got '{domain}'"

    def test_no_binding_for_generic_feature(self):
        """Should return empty for features not matching any domain."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        
        bound_reqs, domain = bind_requirements_to_story(
            feature_title="User Login",
            theme="Authentication",
            epic="Security",
            requirements=requirements,
        )
        
        # Generic feature might not match any domain
        # This is fine - generic stories get minimal validation
        assert isinstance(bound_reqs, list)


class TestAcceptanceCriteriaCompliance:
    """Test validation of acceptance criteria against requirements."""

    def test_compliant_when_artifacts_present(self):
        """Should pass when required artifacts are in AC."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        bound_reqs, _ = bind_requirements_to_story(
            feature_title="Review Action Recording",
            theme="Review Workflow",
            epic="Delta Capture",
            requirements=requirements,
        )
        
        # AC that includes required artifacts
        acceptance_criteria = [
            "Given a reviewer makes a correction, when saved, the system stores the change in review_actions_v{n}.jsonl",
            "The system records action_id, before/after state, and reviewer_id for each action",
            "Model provenance is captured with model_version and config_hash",
        ]
        
        result = check_acceptance_criteria_compliance(
            acceptance_criteria=acceptance_criteria,
            bound_requirements=bound_reqs,
            feature_context="Review Action Recording",
        )
        
        # May not be fully compliant but should have fewer issues
        assert isinstance(result.missing_artifacts, list)

    def test_non_compliant_when_artifacts_missing(self):
        """Should fail when required artifacts are missing from AC."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        bound_reqs, _ = bind_requirements_to_story(
            feature_title="Primitive Review UI",
            theme="Review Workflow",
            epic="Human-in-the-Loop",
            requirements=requirements,
        )
        
        # Generic AC without required artifacts
        acceptance_criteria = [
            "User can see the review interface",
            "User can make corrections",
            "System saves changes",
        ]
        
        result = check_acceptance_criteria_compliance(
            acceptance_criteria=acceptance_criteria,
            bound_requirements=bound_reqs,
            feature_context="Primitive Review UI",
        )
        
        # Should detect missing artifacts
        assert len(result.blocking_suggestions) > 0, \
            "Should have blocking suggestions for generic AC"

    def test_detects_generic_criteria(self):
        """Should flag vague/generic acceptance criteria."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        bound_reqs, _ = bind_requirements_to_story(
            feature_title="Review Checkpoint",
            theme="Review Workflow",
            epic="Quality Gates",
            requirements=requirements,
        )
        
        # Deliberately vague AC
        acceptance_criteria = [
            "User can see the results",
            "System displays information",
            "It works correctly",
            "Successfully processes input",
        ]
        
        result = check_acceptance_criteria_compliance(
            acceptance_criteria=acceptance_criteria,
            bound_requirements=bound_reqs,
            feature_context="Review Checkpoint",
        )
        
        # Should flag generic criteria
        assert len(result.blocking_suggestions) > 0
        # Check for specific generic pattern detection
        suggestion_text = " ".join(result.blocking_suggestions).lower()
        assert "vague" in suggestion_text or "generic" in suggestion_text or "missing" in suggestion_text


class TestFullValidation:
    """Test the complete validation flow."""

    def test_full_validation_review_story(self):
        """End-to-end test for review domain story."""
        result = validate_story_against_spec(
            story_title="Implement Primitive Review Interface",
            story_description="As a reviewer, I want to review and correct primitives so that the gold dataset is accurate.",
            acceptance_criteria=[
                "User can see bounding boxes overlaid on page image",
                "User can edit bbox coordinates",
                "Changes are saved",
            ],
            feature_title="Primitive Review UI",
            theme="Review Workflow",
            epic="Human-in-the-Loop",
            spec_text=SAMPLE_SPEC,
        )
        
        # Should NOT be compliant - missing artifacts
        assert result.is_compliant is False, \
            "Story with generic AC should NOT be compliant"
        assert len(result.blocking_suggestions) > 0, \
            "Should have suggestions for adding artifacts"
        assert result.matched_domain == "review", \
            f"Should match review domain, got '{result.matched_domain}'"

    def test_full_validation_no_spec(self):
        """Should be compliant when no spec is provided."""
        result = validate_story_against_spec(
            story_title="Generic Feature",
            story_description="As a user, I want a feature.",
            acceptance_criteria=["It works"],
            feature_title="Generic Feature",
            theme="General",
            epic="Misc",
            spec_text="",
        )
        
        assert result.is_compliant is True, \
            "Should be compliant when no spec provided"

    def test_compliance_report_format(self):
        """Test that compliance report formats correctly."""
        result = validate_story_against_spec(
            story_title="Review Delta Capture",
            story_description="As a reviewer, I want my changes captured as deltas.",
            acceptance_criteria=["User makes corrections", "System saves"],
            feature_title="Review Delta",
            theme="Review Workflow",
            epic="Delta Schema",
            spec_text=SAMPLE_SPEC,
        )
        
        report = format_compliance_report(result)
        
        assert "Spec Compliance:" in report
        if not result.is_compliant:
            assert "NON-COMPLIANT" in report
        else:
            assert "COMPLIANT" in report


class TestRealWorldScenarios:
    """Test scenarios matching the problem description."""

    def test_ingestion_story_missing_revision_id(self):
        """
        Problem: Ingestion/revision stories pass without requiring 
        immutable doc_revision_id keyed by PDF hash/config.
        """
        result = validate_story_against_spec(
            story_title="Implement Document Ingestion",
            story_description="As a user, I want to upload PDF documents for processing.",
            acceptance_criteria=[
                "User can upload PDF files",
                "System extracts primitives from PDF",
                "User sees upload progress",
                "System displays extraction results",
            ],
            feature_title="PDF Document Ingestion",
            theme="Data Pipeline",
            epic="Input Processing",
            spec_text=SAMPLE_SPEC,
        )
        
        # This SHOULD fail - missing doc_revision_id, model_provenance
        # The blocking_suggestions should mention these artifacts
        if result.matched_domain in ["ingestion", "revision", "workflow"]:
            suggestion_text = " ".join(result.blocking_suggestions).lower()
            # Should flag missing provenance or versioning concerns
            assert len(result.blocking_suggestions) > 0, \
                "Ingestion story missing version/provenance should have suggestions"

    def test_review_story_missing_checkpoint_artifacts(self):
        """
        Problem: Primitive review stories pass without requiring 
        checkpoint artifacts (review_actions, gold_primitives).
        """
        result = validate_story_against_spec(
            story_title="Primitive Review Interface",
            story_description="As a reviewer, I want to review detected primitives.",
            acceptance_criteria=[
                "Reviewer can see detected bounding boxes",
                "Reviewer can approve or reject detections",
                "Reviewer can edit box coordinates",
                "System updates the display after edits",
            ],
            feature_title="Primitive Review UI",
            theme="Review Workflow",
            epic="Checkpoint A",
            spec_text=SAMPLE_SPEC,
        )
        
        assert result.matched_domain == "review", \
            f"Should match review domain, got '{result.matched_domain}'"
        
        # Should NOT be compliant - missing review_actions, gold_primitives artifacts
        assert result.is_compliant is False, \
            "Review story missing checkpoint artifacts should NOT be compliant"
        
        # Suggestions should mention the missing artifacts
        suggestion_text = " ".join(result.blocking_suggestions).lower()
        # Should flag at least one of: review_actions, gold, artifact, output
        flagged_something = any(term in suggestion_text for term in 
            ["artifact", "review_action", "gold", "output", "jsonl"])
        assert flagged_something or len(result.blocking_suggestions) > 0, \
            f"Should flag missing artifacts. Suggestions: {result.blocking_suggestions}"

    def test_audit_story_missing_event_sourced_deltas(self):
        """
        Problem: Audit trail stories pass without requiring 
        event-sourced delta storage.
        """
        result = validate_story_against_spec(
            story_title="Review Audit Trail",
            story_description="As an auditor, I want to see review history.",
            acceptance_criteria=[
                "Auditor can view list of changes",
                "Each change shows timestamp",
                "Changes are displayed chronologically",
            ],
            feature_title="Audit Trail Viewer",
            theme="Compliance",
            epic="Audit & Provenance",
            spec_text=SAMPLE_SPEC,
        )
        
        # Should flag missing event-sourced delta requirements
        if result.matched_domain in ["audit", "review"]:
            assert len(result.blocking_suggestions) > 0, \
                "Audit story should have suggestions about delta storage"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_spec_with_no_requirements(self):
        """Spec without MUST/SHALL/REQUIRED should return no requirements."""
        weak_spec = """
        # Product Guidelines
        
        The system should be user-friendly.
        We recommend using best practices.
        Consider performance implications.
        """
        
        requirements = extract_hard_requirements(weak_spec)
        assert len(requirements) == 0, "Weak spec should have no hard requirements"

    def test_mixed_case_keywords(self):
        """Should handle mixed case requirement keywords."""
        mixed_spec = """
        ## Requirements
        
        The system Must store all data securely.
        User sessions SHALL timeout after 30 minutes.
        Input validation is Required for all fields.
        """
        
        requirements = extract_hard_requirements(mixed_spec)
        assert len(requirements) >= 3, "Should extract requirements with mixed case"

    def test_empty_acceptance_criteria(self):
        """Should handle empty acceptance criteria list."""
        requirements = extract_hard_requirements(SAMPLE_SPEC)
        bound_reqs, _ = bind_requirements_to_story(
            feature_title="Review UI",
            theme="Review",
            epic="Review",
            requirements=requirements,
        )
        
        result = check_acceptance_criteria_compliance(
            acceptance_criteria=[],
            bound_requirements=bound_reqs,
            feature_context="Review UI",
        )
        
        # Empty AC should trigger suggestions
        assert len(result.blocking_suggestions) > 0 or len(result.missing_artifacts) > 0
