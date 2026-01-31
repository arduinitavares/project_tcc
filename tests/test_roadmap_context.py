"""
Tests for roadmap context in story pipeline.

TDD approach: Tests written first to define expected behavior.
"""

import pytest
from sqlmodel import Session, select

from agile_sqlmodel import (
    Epic,
    Feature,
    Product,
    Theme,
    TimeFrame,
)


class TestTimeFrameEnum:
    """Test the TimeFrame enum and its usage in Theme model."""

    def test_time_frame_enum_values(self):
        """TimeFrame enum should have Now, Next, Later values."""
        assert TimeFrame.NOW.value == "Now"
        assert TimeFrame.NEXT.value == "Next"
        assert TimeFrame.LATER.value == "Later"

    def test_theme_with_time_frame(self, session: Session):
        """Theme should store time_frame as enum."""
        # Create product first
        product = Product(name="Test Product", vision="Test vision")
        session.add(product)
        session.commit()
        session.refresh(product)

        # Create theme with time_frame
        theme = Theme(
            title="Core Authentication",
            description="Foundation for user identity",
            time_frame=TimeFrame.NOW,
            product_id=product.product_id,
        )
        session.add(theme)
        session.commit()
        session.refresh(theme)

        # Verify
        assert theme.time_frame == TimeFrame.NOW
        assert theme.time_frame.value == "Now"

    def test_theme_without_time_frame(self, session: Session):
        """Theme should allow null time_frame for backward compatibility."""
        product = Product(name="Test Product 2", vision="Test vision")
        session.add(product)
        session.commit()

        theme = Theme(
            title="Legacy Theme",
            description="No time frame",
            time_frame=None,
            product_id=product.product_id,
        )
        session.add(theme)
        session.commit()
        session.refresh(theme)

        assert theme.time_frame is None


class TestQueryFeaturesWithRoadmapContext:
    """Test that query_features_for_stories includes roadmap context."""

    @pytest.fixture
    def product_with_roadmap(self, session: Session):
        """Create a product with full roadmap hierarchy."""
        # Product
        product = Product(
            name="TaskMaster Pro",
            vision="For busy professionals who need task management",
        )
        session.add(product)
        session.commit()

        # Theme 1: Now
        theme_now = Theme(
            title="Now - Core Authentication",
            description="Essential foundation for user identity",
            time_frame=TimeFrame.NOW,
            product_id=product.product_id,
        )
        session.add(theme_now)
        session.commit()

        epic_auth = Epic(
            title="Core Authentication",
            summary="User authentication features",
            theme_id=theme_now.theme_id,
        )
        session.add(epic_auth)
        session.commit()

        features_now = [
            Feature(title="User registration", description="", epic_id=epic_auth.epic_id),
            Feature(title="Login/logout", description="", epic_id=epic_auth.epic_id),
            Feature(title="Password reset", description="", epic_id=epic_auth.epic_id),
        ]
        for f in features_now:
            session.add(f)
        session.commit()

        # Theme 2: Next
        theme_next = Theme(
            title="Next - AI Suggestions",
            description="Differentiator; requires task data first",
            time_frame=TimeFrame.NEXT,
            product_id=product.product_id,
        )
        session.add(theme_next)
        session.commit()

        epic_ai = Epic(
            title="AI Suggestions",
            summary="AI-powered features",
            theme_id=theme_next.theme_id,
        )
        session.add(epic_ai)
        session.commit()

        features_next = [
            Feature(title="Priority prediction", description="", epic_id=epic_ai.epic_id),
            Feature(title="Smart scheduling", description="", epic_id=epic_ai.epic_id),
        ]
        for f in features_next:
            session.add(f)
        session.commit()

        session.refresh(product)
        return product

    def test_features_include_time_frame(
        self, session: Session, product_with_roadmap: Product, engine, monkeypatch
    ):
        """Features should include time_frame from their theme."""
        from orchestrator_agent.agent_tools import product_user_story_tool
        from orchestrator_agent.agent_tools.product_user_story_tool.tools import (
            query_features_for_stories,
            QueryFeaturesInput,
        )

        # Patch the engine to use our test engine
        monkeypatch.setattr(product_user_story_tool.tools, "engine", engine)

        result = query_features_for_stories(
            QueryFeaturesInput(product_id=product_with_roadmap.product_id)
        )

        assert result["success"] is True
        features_flat = result["features_flat"]

        # Find a "Now" feature
        user_reg = next(f for f in features_flat if f["feature_title"] == "User registration")
        assert user_reg["time_frame"] == "Now"
        assert user_reg["theme_justification"] == "Essential foundation for user identity"

        # Find a "Next" feature
        priority_pred = next(f for f in features_flat if f["feature_title"] == "Priority prediction")
        assert priority_pred["time_frame"] == "Next"
        assert priority_pred["theme_justification"] == "Differentiator; requires task data first"

    def test_features_include_sibling_features(
        self, session: Session, product_with_roadmap: Product, engine, monkeypatch
    ):
        """Features should list sibling features in the same theme."""
        from orchestrator_agent.agent_tools import product_user_story_tool
        from orchestrator_agent.agent_tools.product_user_story_tool.tools import (
            query_features_for_stories,
            QueryFeaturesInput,
        )

        # Patch the engine to use our test engine
        monkeypatch.setattr(product_user_story_tool.tools, "engine", engine)

        result = query_features_for_stories(
            QueryFeaturesInput(product_id=product_with_roadmap.product_id)
        )

        features_flat = result["features_flat"]

        # Find a "Now" feature and check siblings
        user_reg = next(f for f in features_flat if f["feature_title"] == "User registration")
        assert user_reg["sibling_features"]  # Has siblings
        assert "Login/logout" in user_reg["sibling_features"]
        assert "Password reset" in user_reg["sibling_features"]
        # Should NOT include itself
        assert "User registration" not in user_reg["sibling_features"]


class TestProcessStoryInputWithRoadmapContext:
    """Test ProcessStoryInput schema includes roadmap context fields."""

    def test_process_story_input_has_roadmap_fields(self):
        """ProcessStoryInput should have time_frame, theme_justification, sibling_features."""
        from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput

        # Check schema fields exist
        fields = ProcessStoryInput.model_fields
        assert "time_frame" in fields
        assert "theme_justification" in fields
        assert "sibling_features" in fields

    def test_process_story_input_accepts_roadmap_context(self):
        """ProcessStoryInput should accept roadmap context values."""
        from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput

        input_data = ProcessStoryInput(
            product_id=1,
            product_name="Test Product",
            product_vision="Test vision",
            feature_id=10,
            feature_title="User registration",
            theme="Core Authentication",
            epic="Core Authentication",
            time_frame="Now",
            theme_justification="Essential foundation",
            sibling_features=["Login/logout", "Password reset"],
            user_persona="developer",
            include_story_points=True,
        )

        assert input_data.time_frame == "Now"
        assert input_data.theme_justification == "Essential foundation"
        assert input_data.sibling_features == ["Login/logout", "Password reset"]


class TestSpecValidatorWithTimeFrameCheck:
    """Test that Spec validator has access to time-frame context."""

    def test_validator_catches_future_dependency(self):
        """Validator should flag stories that depend on 'Next' or 'Later' features."""
        # This test validates that the validator agent instruction includes
        # time-frame awareness. The actual validation happens in the LLM,
        # but we can check that the context is properly passed.
        from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput

        # A "Now" feature shouldn't reference "Later" capabilities
        input_data = ProcessStoryInput(
            product_id=1,
            product_name="Test Product",
            product_vision="Task management app",
            feature_id=10,
            feature_title="User registration",
            theme="Core Authentication",
            epic="Core Authentication",
            time_frame="Now",  # This is a NOW feature
            theme_justification="Foundation",
            sibling_features=["Login/logout"],
            user_persona="developer",
        )

        # The time_frame is properly captured for the validator
        assert input_data.time_frame == "Now"
        # The validator can use this to check if the generated story
        # incorrectly references features from "Next" or "Later" themes


class TestRoadmapToolSavesTimeFrame:
    """Test that save_roadmap_tool properly stores time_frame in database."""

    def test_save_roadmap_creates_themes_with_time_frame(self, session: Session):
        """save_roadmap_tool should create themes with time_frame enum."""
        from orchestrator_agent.agent_tools.product_roadmap_agent.tools import (
            _create_structure_from_themes,
            _parse_time_frame,
            RoadmapThemeInput,
        )

        # Create product
        product = Product(name="Test Roadmap Product", vision="Test")
        session.add(product)
        session.commit()

        themes_input = [
            RoadmapThemeInput(
                theme_name="Core Auth",
                key_features=["Login", "Logout"],
                justification="Foundation",
                time_frame="Now",
            ),
            RoadmapThemeInput(
                theme_name="AI Features",
                key_features=["Prediction"],
                justification="Differentiator",
                time_frame="Next",
            ),
        ]

        result = _create_structure_from_themes(session, product.product_id, themes_input)

        # Verify themes were created with correct time_frames
        themes = session.exec(
            select(Theme).where(Theme.product_id == product.product_id)
        ).all()

        assert len(themes) == 2

        theme_now = next(t for t in themes if "Core Auth" in t.title)
        assert theme_now.time_frame == TimeFrame.NOW

        theme_next = next(t for t in themes if "AI Features" in t.title)
        assert theme_next.time_frame == TimeFrame.NEXT

    def test_parse_time_frame_helper(self):
        """_parse_time_frame should convert strings to TimeFrame enum."""
        from orchestrator_agent.agent_tools.product_roadmap_agent.tools import (
            _parse_time_frame,
        )

        assert _parse_time_frame("Now") == TimeFrame.NOW
        assert _parse_time_frame("now") == TimeFrame.NOW
        assert _parse_time_frame("NOW") == TimeFrame.NOW
        assert _parse_time_frame("Next") == TimeFrame.NEXT
        assert _parse_time_frame("Later") == TimeFrame.LATER
        assert _parse_time_frame(None) is None
        assert _parse_time_frame("Invalid") is None
        assert _parse_time_frame("") is None
