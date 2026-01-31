# tests/test_story_validation_pinning.py
"""
Tests for Story Validation Pinning v2.

These tests validate that:
- Validation REQUIRES explicit spec_version_id (no defaults)
- Validation fails fast if spec is not compiled
- Evidence is ALWAYS persisted (pass or fail)
- accepted_spec_version_id is only set on pass
- Input hashing is deterministic
- Wrong spec_version_id fails deterministically
"""

import json

import pytest
from pydantic import ValidationError
from sqlmodel import Session

from agile_sqlmodel import (
    Epic,
    Feature,
    Product,
    SpecRegistry,
    Theme,
    UserStory,
)
import tools.spec_tools as spec_tools
from tools.spec_tools import (
    VALIDATOR_VERSION,
    ValidateStoryInput,
    approve_spec_version,
    compile_spec_authority,
    register_spec_version,
    validate_story_with_spec_authority,
)
from utils.schemes import ValidationEvidence


@pytest.fixture
def sample_product(session: Session, engine) -> Product:
    """Create a product for testing."""
    spec_tools.engine = engine

    product = Product(
        name="Validation Test Product",
        description="Product for validation pinning tests",
        vision="Test validation pinning",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@pytest.fixture
def compiled_spec(session: Session, sample_product: Product) -> SpecRegistry:
    """Create a registered, approved, and compiled spec version."""
    spec_content = """
# Test Specification

## Requirements
- All stories MUST have acceptance criteria
- Stories MUST follow the "As a [persona]" format
- Export formats: JSON only

## Invariants
- Auth token required for all operations
- Maximum 10 items per page
"""
    reg_result = register_spec_version(
        {"product_id": sample_product.product_id, "content": spec_content},
        tool_context=None,
    )
    spec_version_id = reg_result["spec_version_id"]

    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "test_reviewer"},
        tool_context=None,
    )

    compile_spec_authority(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )

    spec = session.get(SpecRegistry, spec_version_id)
    session.refresh(spec)
    return spec


@pytest.fixture
def sample_story(session: Session, sample_product: Product) -> UserStory:
    """Create a user story for testing (with full hierarchy)."""
    theme = Theme(
        product_id=sample_product.product_id,
        title="Test Theme",
        description="Theme for validation tests",
    )
    session.add(theme)
    session.commit()
    session.refresh(theme)

    epic = Epic(
        theme_id=theme.theme_id,
        title="Test Epic",
        description="Epic for validation tests",
    )
    session.add(epic)
    session.commit()
    session.refresh(epic)

    feature = Feature(
        epic_id=epic.epic_id,
        title="Test Feature",
        description="Feature for validation tests",
    )
    session.add(feature)
    session.commit()
    session.refresh(feature)

    story = UserStory(
        product_id=sample_product.product_id,
        feature_id=feature.feature_id,
        title="As a user, I want to export data",
        story_description=(
            "As a user, I want to export my data in JSON format so I can use it elsewhere."
        ),
        acceptance_criteria=(
            "Given I have data, When I click export, Then I receive a JSON file"
        ),
    )
    session.add(story)
    session.commit()
    session.refresh(story)
    return story


class TestFailFastWithoutSpecVersionId:
    """Tests that validation fails immediately without spec_version_id."""

    def test_validation_requires_spec_version_id_in_schema(self):
        """Input schema requires spec_version_id (no default)."""
        with pytest.raises(ValidationError) as exc_info:
            ValidateStoryInput(story_id=1)

        errors = exc_info.value.errors()
        assert any("spec_version_id" in str(e) for e in errors)

    def test_validation_rejects_none_spec_version_id(self):
        """spec_version_id=None is rejected."""
        with pytest.raises(ValidationError):
            ValidateStoryInput(story_id=1, spec_version_id=None)


class TestFailFastIfNotCompiled:
    """Tests that validation fails if spec is not compiled."""

    def test_validation_fails_for_nonexistent_spec_version(
        self, sample_story: UserStory, engine
    ):
        """Clear error when spec_version_id doesn't exist."""
        spec_tools.engine = engine

        result = validate_story_with_spec_authority(
            {"story_id": sample_story.story_id, "spec_version_id": 99999},
            tool_context=None,
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_validation_fails_for_uncompiled_spec(
        self, sample_product: Product, sample_story: UserStory, engine
    ):
        """Clear error when spec exists but is not compiled."""
        spec_tools.engine = engine

        reg_result = register_spec_version(
            {"product_id": sample_product.product_id, "content": "Draft spec content"},
            tool_context=None,
        )
        spec_version_id = reg_result["spec_version_id"]

        result = validate_story_with_spec_authority(
            {"story_id": sample_story.story_id, "spec_version_id": spec_version_id},
            tool_context=None,
        )

        assert result["success"] is False
        assert "not compiled" in result["error"].lower()

    def test_validation_fails_for_approved_but_uncompiled_spec(
        self, sample_product: Product, sample_story: UserStory, engine
    ):
        """Approved but uncompiled spec fails with clear message."""
        spec_tools.engine = engine

        reg_result = register_spec_version(
            {"product_id": sample_product.product_id, "content": "Approved but not compiled"},
            tool_context=None,
        )
        spec_version_id = reg_result["spec_version_id"]

        approve_spec_version(
            {"spec_version_id": spec_version_id, "approved_by": "reviewer"},
            tool_context=None,
        )

        result = validate_story_with_spec_authority(
            {"story_id": sample_story.story_id, "spec_version_id": spec_version_id},
            tool_context=None,
        )

        assert result["success"] is False
        assert "not compiled" in result["error"].lower()


class TestEvidencePersistence:
    """Tests that validation evidence is ALWAYS persisted."""

    def test_evidence_persisted_on_validation_pass(
        self,
        session: Session,
        sample_story: UserStory,
        compiled_spec: SpecRegistry,
        engine,
    ):
        """Evidence is stored when validation passes."""
        spec_tools.engine = engine

        result = validate_story_with_spec_authority(
            {"story_id": sample_story.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )

        session.expire(sample_story)
        story = session.get(UserStory, sample_story.story_id)

        assert story.validation_evidence is not None
        evidence = json.loads(story.validation_evidence)

        assert evidence["spec_version_id"] == compiled_spec.spec_version_id
        assert "validated_at" in evidence
        assert "passed" in evidence
        assert "rules_checked" in evidence
        assert "invariants_checked" in evidence
        assert "validator_version" in evidence
        assert "input_hash" in evidence

        if result.get("passed", False):
            assert story.accepted_spec_version_id == compiled_spec.spec_version_id

    def test_evidence_persisted_on_validation_fail(
        self,
        session: Session,
        sample_product: Product,
        compiled_spec: SpecRegistry,
        engine,
    ):
        """Evidence is stored even when validation fails."""
        spec_tools.engine = engine

        theme = Theme(
            product_id=sample_product.product_id,
            title="Fail Theme",
            description="Theme for fail test",
        )
        session.add(theme)
        session.commit()

        epic = Epic(theme_id=theme.theme_id, title="Fail Epic", description="Epic for fail test")
        session.add(epic)
        session.commit()

        feature = Feature(
            epic_id=epic.epic_id, title="Fail Feature", description="Feature for fail test"
        )
        session.add(feature)
        session.commit()

        bad_story = UserStory(
            product_id=sample_product.product_id,
            feature_id=feature.feature_id,
            title="Bad story title",
            story_description="This is a poorly formatted story",
            acceptance_criteria="",
        )
        session.add(bad_story)
        session.commit()
        session.refresh(bad_story)

        original_accepted = bad_story.accepted_spec_version_id

        validate_story_with_spec_authority(
            {"story_id": bad_story.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )

        session.expire(bad_story)
        story = session.get(UserStory, bad_story.story_id)

        assert story.validation_evidence is not None
        evidence = json.loads(story.validation_evidence)
        assert evidence["spec_version_id"] == compiled_spec.spec_version_id
        assert "failures" in evidence

        assert story.accepted_spec_version_id == original_accepted

    def test_evidence_contains_all_required_fields(
        self,
        session: Session,
        sample_story: UserStory,
        compiled_spec: SpecRegistry,
        engine,
    ):
        """Evidence contains all required fields per schema."""
        spec_tools.engine = engine

        validate_story_with_spec_authority(
            {"story_id": sample_story.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )

        session.expire(sample_story)
        story = session.get(UserStory, sample_story.story_id)
        evidence = json.loads(story.validation_evidence)

        validated = ValidationEvidence.model_validate(evidence)

        assert validated.spec_version_id == compiled_spec.spec_version_id
        assert validated.validator_version == VALIDATOR_VERSION
        assert isinstance(validated.rules_checked, list)
        assert isinstance(validated.invariants_checked, list)
        assert isinstance(validated.failures, list)
        assert isinstance(validated.warnings, list)
        assert validated.input_hash is not None


class TestDeterministicInputHashing:
    """Tests that input hashing is deterministic and reproducible."""

    def test_same_story_content_produces_same_hash(
        self,
        session: Session,
        sample_product: Product,
        compiled_spec: SpecRegistry,
        engine,
    ):
        """Identical story content produces identical input_hash."""
        spec_tools.engine = engine

        theme = Theme(product_id=sample_product.product_id, title="Hash Theme", description="")
        session.add(theme)
        session.commit()

        epic = Epic(theme_id=theme.theme_id, title="Hash Epic", description="")
        session.add(epic)
        session.commit()

        feature = Feature(epic_id=epic.epic_id, title="Hash Feature", description="")
        session.add(feature)
        session.commit()

        story_content = {
            "title": "As a tester, I want determinism",
            "description": "As a tester, I want deterministic hashing for reproducibility.",
            "acceptance_criteria": "Given input X, When hashed, Then hash is always Y",
        }

        story1 = UserStory(
            product_id=sample_product.product_id,
            feature_id=feature.feature_id,
            title=story_content["title"],
            story_description=story_content["description"],
            acceptance_criteria=story_content["acceptance_criteria"],
        )
        session.add(story1)
        session.commit()
        session.refresh(story1)

        story2 = UserStory(
            product_id=sample_product.product_id,
            feature_id=feature.feature_id,
            title=story_content["title"],
            story_description=story_content["description"],
            acceptance_criteria=story_content["acceptance_criteria"],
        )
        session.add(story2)
        session.commit()
        session.refresh(story2)

        validate_story_with_spec_authority(
            {"story_id": story1.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )
        validate_story_with_spec_authority(
            {"story_id": story2.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )

        session.expire_all()
        s1 = session.get(UserStory, story1.story_id)
        s2 = session.get(UserStory, story2.story_id)

        e1 = json.loads(s1.validation_evidence)
        e2 = json.loads(s2.validation_evidence)

        assert e1["input_hash"] == e2["input_hash"]

    def test_different_story_content_produces_different_hash(
        self,
        session: Session,
        sample_product: Product,
        compiled_spec: SpecRegistry,
        engine,
    ):
        """Different story content produces different input_hash."""
        spec_tools.engine = engine

        theme = Theme(product_id=sample_product.product_id, title="Diff Theme", description="")
        session.add(theme)
        session.commit()

        epic = Epic(theme_id=theme.theme_id, title="Diff Epic", description="")
        session.add(epic)
        session.commit()

        feature = Feature(epic_id=epic.epic_id, title="Diff Feature", description="")
        session.add(feature)
        session.commit()

        story1 = UserStory(
            product_id=sample_product.product_id,
            feature_id=feature.feature_id,
            title="Story A",
            story_description="Description A",
            acceptance_criteria="AC A",
        )
        session.add(story1)
        session.commit()
        session.refresh(story1)

        story2 = UserStory(
            product_id=sample_product.product_id,
            feature_id=feature.feature_id,
            title="Story B",
            story_description="Description B",
            acceptance_criteria="AC B",
        )
        session.add(story2)
        session.commit()
        session.refresh(story2)

        validate_story_with_spec_authority(
            {"story_id": story1.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )
        validate_story_with_spec_authority(
            {"story_id": story2.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )

        session.expire_all()
        s1 = session.get(UserStory, story1.story_id)
        s2 = session.get(UserStory, story2.story_id)

        e1 = json.loads(s1.validation_evidence)
        e2 = json.loads(s2.validation_evidence)

        assert e1["input_hash"] != e2["input_hash"]


class TestWrongSpecVersionIdFails:
    """Tests that using wrong spec_version_id fails deterministically."""

    def test_validation_fails_for_spec_from_different_product(
        self,
        session: Session,
        sample_product: Product,
        sample_story: UserStory,
        compiled_spec: SpecRegistry,
        engine,
    ):
        """Validation fails if spec belongs to different product."""
        spec_tools.engine = engine

        other_product = Product(
            name="Other Product",
            description="Different product",
            vision="Different vision",
        )
        session.add(other_product)
        session.commit()
        session.refresh(other_product)

        reg_result = register_spec_version(
            {"product_id": other_product.product_id, "content": "Other product spec"},
            tool_context=None,
        )
        other_spec_id = reg_result["spec_version_id"]

        approve_spec_version(
            {"spec_version_id": other_spec_id, "approved_by": "reviewer"},
            tool_context=None,
        )
        compile_spec_authority(
            {"spec_version_id": other_spec_id},
            tool_context=None,
        )

        result = validate_story_with_spec_authority(
            {"story_id": sample_story.story_id, "spec_version_id": other_spec_id},
            tool_context=None,
        )

        assert result["success"] is False
        assert "product" in result["error"].lower() or "mismatch" in result["error"].lower()


class TestValidatorVersion:
    """Tests for validator versioning."""

    def test_validator_version_constant_exists(self):
        """VALIDATOR_VERSION constant exists."""
        assert VALIDATOR_VERSION is not None
        assert isinstance(VALIDATOR_VERSION, str)
        parts = VALIDATOR_VERSION.split(".")
        assert len(parts) >= 2

    def test_validator_version_in_evidence(
        self,
        session: Session,
        sample_story: UserStory,
        compiled_spec: SpecRegistry,
        engine,
    ):
        """validator_version is stored in evidence."""
        spec_tools.engine = engine

        validate_story_with_spec_authority(
            {"story_id": sample_story.story_id, "spec_version_id": compiled_spec.spec_version_id},
            tool_context=None,
        )

        session.expire(sample_story)
        story = session.get(UserStory, sample_story.story_id)
        evidence = json.loads(story.validation_evidence)

        assert evidence["validator_version"] == VALIDATOR_VERSION