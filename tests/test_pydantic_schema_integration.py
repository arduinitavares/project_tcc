"""
Test Pydantic Schema Integration for Theme/Epic Enforcement.

This test verifies that:
1. query_features_for_stories returns QueryFeaturesOutput with validated FeatureForStory objects
2. FeatureForStory enforces theme/epic min_length=1 (no empty strings)
3. Orchestrator cannot bypass validation by constructing dicts manually
"""

import pytest
from pydantic import ValidationError
from sqlmodel import Session

from agile_sqlmodel import engine
from tools.story_query_tools import (
    FeatureForStory,
    QueryFeaturesOutput,
    QueryFeaturesInput,
    query_features_for_stories,
)


class TestPydanticSchemaEnforcement:
    """Verify Pydantic schemas enforce theme/epic presence at compile-time."""

    def test_feature_for_story_requires_theme(self):
        """FeatureForStory must have theme with min_length=1."""
        with pytest.raises(ValidationError) as exc_info:
            FeatureForStory(
                feature_id=1,
                feature_title="Test Feature",
                theme="",  # Empty string should fail
                epic="Valid Epic",
            )
        
        # Verify the error message mentions string constraints
        assert "theme" in str(exc_info.value).lower()

    def test_feature_for_story_requires_epic(self):
        """FeatureForStory must have epic with min_length=1."""
        with pytest.raises(ValidationError) as exc_info:
            FeatureForStory(
                feature_id=1,
                feature_title="Test Feature",
                theme="Valid Theme",
                epic="",  # Empty string should fail
            )
        
        assert "epic" in str(exc_info.value).lower()

    def test_feature_for_story_rejects_none_theme(self):
        """FeatureForStory must not accept None for theme."""
        with pytest.raises(ValidationError) as exc_info:
            FeatureForStory(
                feature_id=1,
                feature_title="Test Feature",
                theme=None,  # None should fail
                epic="Valid Epic",
            )
        
        assert "theme" in str(exc_info.value).lower()

    def test_feature_for_story_rejects_none_epic(self):
        """FeatureForStory must not accept None for epic."""
        with pytest.raises(ValidationError) as exc_info:
            FeatureForStory(
                feature_id=1,
                feature_title="Test Feature",
                theme="Valid Theme",
                epic=None,  # None should fail
            )
        
        assert "epic" in str(exc_info.value).lower()

    def test_feature_for_story_valid_creation(self):
        """FeatureForStory accepts valid theme and epic."""
        feature = FeatureForStory(
            feature_id=1,
            feature_title="Test Feature",
            theme="Valid Theme",
            epic="Valid Epic",
            theme_id=1,
            epic_id=1,
        )
        
        assert feature.theme == "Valid Theme"
        assert feature.epic == "Valid Epic"
        assert feature.feature_id == 1

    def test_query_features_output_structure(self):
        """QueryFeaturesOutput enforces List[FeatureForStory]."""
        # Valid structure
        output = QueryFeaturesOutput(
            success=True,
            product_id=1,
            product_name="Test Product",
            features_flat=[
                FeatureForStory(
                    feature_id=1,
                    feature_title="Feature 1",
                    theme="Theme A",
                    epic="Epic X",
                    theme_id=1,
                    epic_id=1,
                )
            ],
            structure=[],
            total_features=1,
            message="Success",
        )
        
        assert output.success is True
        assert len(output.features_flat) == 1
        assert output.features_flat[0].theme == "Theme A"

    def test_query_features_output_rejects_invalid_features(self):
        """QueryFeaturesOutput rejects features with empty theme/epic."""
        with pytest.raises(ValidationError):
            QueryFeaturesOutput(
                success=True,
                product_id=1,
                product_name="Test Product",
                features_flat=[
                    FeatureForStory(
                        feature_id=1,
                        feature_title="Feature 1",
                        theme="",  # Empty theme should fail
                        epic="Epic X",
                    )
                ],
                structure=[],
                total_features=1,
                message="Success",
            )


    def test_query_features_for_stories_returns_validated_output(self, engine):
        """query_features_for_stories returns dict from QueryFeaturesOutput."""
        from agile_sqlmodel import Theme, Epic, Feature, Product
        import tools.story_query_tools as story_tools

        story_tools.engine = engine

        with Session(engine) as session:
            product = Product(name="Test Product", vision="Test")
            session.add(product)
            session.commit()
            session.refresh(product)
            product_id = product.product_id

            theme = Theme(title="Theme A", product_id=product.product_id)
            session.add(theme)
            session.commit()
            session.refresh(theme)

            epic = Epic(title="Epic X", theme_id=theme.theme_id)
            session.add(epic)
            session.commit()
            session.refresh(epic)

            feature = Feature(title="Feature 1", epic_id=epic.epic_id)
            session.add(feature)
            session.commit()

        result = query_features_for_stories(QueryFeaturesInput(product_id=product_id))

        assert isinstance(result, dict)
        assert result["success"] is True

        for feature in result["features_flat"]:
            assert isinstance(feature, dict)
            assert feature["theme"]
            assert feature["epic"]
            assert len(feature["theme"]) >= 1
            assert len(feature["epic"]) >= 1
            assert feature["theme"] != "Unknown"
            assert feature["epic"] != "Unknown"


class TestSchemaPreventsDictConstruction:
    """Verify Pydantic prevents manual dict construction bypassing validation."""

    def test_cannot_construct_feature_with_whitespace_theme(self):
        """FeatureForStory rejects whitespace-only theme."""
        with pytest.raises(ValidationError):
            FeatureForStory(
                feature_id=1,
                feature_title="Test Feature",
                theme="   ",  # Whitespace should fail min_length
                epic="Valid Epic",
            )

    def test_cannot_construct_feature_with_whitespace_epic(self):
        """FeatureForStory rejects whitespace-only epic."""
        with pytest.raises(ValidationError):
            FeatureForStory(
                feature_id=1,
                feature_title="Test Feature",
                theme="Valid Theme",
                epic="   ",  # Whitespace should fail min_length
            )


class TestImmutabilityEnforcement:
    """Verify models are frozen/immutable after construction."""

    def test_feature_for_story_is_frozen(self):
        """FeatureForStory cannot be mutated after construction."""
        feature = FeatureForStory(
            feature_id=1,
            feature_title="Test Feature",
            theme="Now - Ingestion",
            epic="Document Processing",
            theme_id=10,
            epic_id=20,
        )
        
        # Attempt to mutate should raise ValidationError
        with pytest.raises(ValidationError):
            feature.theme = "Mutated Theme"
        
        with pytest.raises(ValidationError):
            feature.epic = "Mutated Epic"
        
        with pytest.raises(ValidationError):
            feature.theme_id = 999

    def test_process_story_input_is_frozen(self):
        """ProcessStoryInput cannot be mutated after construction."""
        from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput
        
        story_input = ProcessStoryInput(
            product_id=1,
            product_name="Test Product",
            spec_version_id=1,
            feature_id=42,
            feature_title="Test Feature",
            theme="Now - Ingestion",
            epic="Document Processing",
            theme_id=10,
            epic_id=20,
        )
        
        # Attempt to mutate should raise ValidationError
        with pytest.raises(ValidationError):
            story_input.theme = "Mutated Theme"
        
        with pytest.raises(ValidationError):
            story_input.epic = "Mutated Epic"

    def test_feature_for_story_includes_stable_ids(self):
        """FeatureForStory includes theme_id and epic_id for stable validation."""
        feature = FeatureForStory(
            feature_id=1,
            feature_title="Test Feature",
            theme="Now - Ingestion",
            epic="Document Processing",
            theme_id=10,
            epic_id=20,
        )
        
        assert feature.theme_id == 10
        assert feature.epic_id == 20

    def test_feature_for_story_ids_are_mandatory(self):
        """FeatureForStory requires theme_id and epic_id (no longer optional)."""
        with pytest.raises(ValidationError) as exc_info:
            FeatureForStory(
                feature_id=1,
                feature_title="Test Feature",
                theme="Now - Ingestion",
                epic="Document Processing",
                # Missing theme_id and epic_id should fail
            )
        
        # Verify both fields are mentioned in error
        assert "theme_id" in str(exc_info.value).lower()
        assert "epic_id" in str(exc_info.value).lower()


class TestContractEnforcerIdValidation:
    """Verify contract enforcer validates theme_id/epic_id when present."""

    def test_id_mismatch_detected(self):
        """Contract enforcer catches theme_id/epic_id mismatch."""
        from orchestrator_agent.agent_tools.story_pipeline.util.story_contract_enforcer import (
            enforce_theme_epic_contract,
        )
        
        # Story has wrong IDs
        story = {
            "theme": "Now - Ingestion",
            "epic": "Document Processing",
            "theme_id": 999,  # Wrong!
            "epic_id": 888,   # Wrong!
        }
        
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now - Ingestion",
            expected_epic="Document Processing",
            expected_theme_id=10,  # Expected
            expected_epic_id=20,   # Expected
        )
        
        rules = [v.rule for v in violations]
        assert "STORY_THEME_ID_MISMATCH" in rules
        assert "STORY_EPIC_ID_MISMATCH" in rules

    def test_id_validation_skipped_when_not_provided(self):
        """Contract enforcer skips ID validation when IDs not in story."""
        from orchestrator_agent.agent_tools.story_pipeline.util.story_contract_enforcer import (
            enforce_theme_epic_contract,
        )
        
        # Story has no IDs (backward compatible)
        story = {
            "theme": "Now - Ingestion",
            "epic": "Document Processing",
        }
        
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now - Ingestion",
            expected_epic="Document Processing",
            expected_theme_id=10,
            expected_epic_id=20,
        )
        
        # Should pass - no ID mismatch when story doesn't have IDs
        assert len(violations) == 0

    def test_title_mismatch_still_caught_even_with_ids(self):
        """Title mismatch is caught even when IDs match."""
        from orchestrator_agent.agent_tools.story_pipeline.util.story_contract_enforcer import (
            enforce_theme_epic_contract,
        )
        
        # Story has correct IDs but wrong titles (indicates data corruption)
        story = {
            "theme": "Wrong Theme",  # Mismatch
            "epic": "Document Processing",
            "theme_id": 10,  # Correct
            "epic_id": 20,   # Correct
        }
        
        violations = enforce_theme_epic_contract(
            story=story,
            expected_theme="Now - Ingestion",
            expected_epic="Document Processing",
            expected_theme_id=10,
            expected_epic_id=20,
        )
        
        rules = [v.rule for v in violations]
        assert "STORY_THEME_MISMATCH" in rules
        # No ID mismatch since IDs are correct
        assert "STORY_THEME_ID_MISMATCH" not in rules
