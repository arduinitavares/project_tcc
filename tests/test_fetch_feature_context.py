"""
Tests for fetch_feature_context - the function that derives all pipeline context from feature_id.

TDD: Write tests first for the new simplified architecture where only feature_id is required,
and all other fields (theme, epic, time_frame, product_vision, etc.) are fetched from DB.
"""

import pytest
from sqlmodel import Session, select

from agile_sqlmodel import Product, Theme, Epic, Feature, get_engine


class TestFetchFeatureContext:
    """Test the fetch_feature_context function that derives all context from feature_id."""

    @pytest.fixture
    def seeded_product_with_hierarchy(self, engine):
        """Create a full product hierarchy: Product -> Theme -> Epic -> Feature."""
        with Session(engine) as session:
            product = Product(
                name="Test Product",
                vision="Build the best product",
            )
            session.add(product)
            session.commit()
            session.refresh(product)

            theme = Theme(
                product_id=product.product_id,
                title="Now (Months 1-3) - Core Infrastructure",
                description="Foundation components for the MVP",
                time_frame="Now",
            )
            session.add(theme)
            session.commit()
            session.refresh(theme)

            epic = Epic(
                theme_id=theme.theme_id,
                title="Authentication",
                description="User authentication and authorization",
            )
            session.add(epic)
            session.commit()
            session.refresh(epic)

            feature = Feature(
                epic_id=epic.epic_id,
                title="Login Flow",
                description="Basic login flow for users",
                acceptance_criteria="Given a user, when they login, then they see dashboard",
            )
            session.add(feature)
            session.commit()
            session.refresh(feature)

            return {
                "product_id": product.product_id,
                "product_name": product.name,
                "product_vision": product.vision,
                "theme_id": theme.theme_id,
                "theme_name": theme.title,
                "theme_description": theme.description,
                "time_frame": theme.time_frame,
                "epic_id": epic.epic_id,
                "epic_name": epic.title,
                "feature_id": feature.feature_id,
                "feature_title": feature.title,
            }

    def test_fetch_feature_context_returns_full_hierarchy(self, seeded_product_with_hierarchy, engine):
        """Given a feature_id, should return complete context from DB."""
        from orchestrator_agent.agent_tools.story_pipeline.context_fetcher import fetch_feature_context

        feature_id = seeded_product_with_hierarchy["feature_id"]

        context = fetch_feature_context(feature_id, engine=engine)

        assert context is not None
        # Product-level (note: domain comes from authority, not product)
        assert context["product_id"] == seeded_product_with_hierarchy["product_id"]
        assert context["product_name"] == seeded_product_with_hierarchy["product_name"]
        assert context["product_vision"] == seeded_product_with_hierarchy["product_vision"]
        # Theme-level
        assert context["theme_id"] == seeded_product_with_hierarchy["theme_id"]
        assert context["theme_name"] == seeded_product_with_hierarchy["theme_name"]
        assert context["time_frame"] == seeded_product_with_hierarchy["time_frame"]
        assert context["theme_justification"] == seeded_product_with_hierarchy["theme_description"]
        # Epic-level
        assert context["epic_id"] == seeded_product_with_hierarchy["epic_id"]
        assert context["epic_name"] == seeded_product_with_hierarchy["epic_name"]
        # Feature-level
        assert context["feature_id"] == feature_id
        assert context["feature_title"] == seeded_product_with_hierarchy["feature_title"]

    def test_fetch_feature_context_nonexistent_feature(self, engine):
        """Given a nonexistent feature_id, should return None."""
        from orchestrator_agent.agent_tools.story_pipeline.context_fetcher import fetch_feature_context

        context = fetch_feature_context(99999, engine=engine)

        assert context is None

    def test_fetch_feature_context_derives_time_frame_from_title(self, engine):
        """When theme.time_frame is NULL, should derive from title."""
        from orchestrator_agent.agent_tools.story_pipeline.context_fetcher import fetch_feature_context

        with Session(engine) as session:
            product = Product(name="Fallback Product", vision="Test")
            session.add(product)
            session.commit()
            session.refresh(product)

            # Theme with NULL time_frame but "Later" in title
            theme = Theme(
                product_id=product.product_id,
                title="Later (Months 7-12) - Advanced Features",
                description="Future work",
                time_frame=None,  # NULL - should be derived
            )
            session.add(theme)
            session.commit()
            session.refresh(theme)

            epic = Epic(theme_id=theme.theme_id, title="Epic")
            session.add(epic)
            session.commit()
            session.refresh(epic)

            feature = Feature(epic_id=epic.epic_id, title="Feature")
            session.add(feature)
            session.commit()
            session.refresh(feature)

            feature_id = feature.feature_id

        context = fetch_feature_context(feature_id, engine=engine)

        assert context is not None
        assert context["time_frame"] == "Later"  # Derived from title

    def test_fetch_feature_context_includes_sibling_features(self, engine):
        """Should include other features in the same theme as siblings."""
        from orchestrator_agent.agent_tools.story_pipeline.context_fetcher import fetch_feature_context

        with Session(engine) as session:
            product = Product(name="Sibling Test", vision="Test")
            session.add(product)
            session.commit()
            session.refresh(product)

            theme = Theme(product_id=product.product_id, title="Theme", time_frame="Now")
            session.add(theme)
            session.commit()
            session.refresh(theme)

            epic1 = Epic(theme_id=theme.theme_id, title="Epic 1")
            epic2 = Epic(theme_id=theme.theme_id, title="Epic 2")
            session.add_all([epic1, epic2])
            session.commit()
            session.refresh(epic1)
            session.refresh(epic2)

            feature_a = Feature(epic_id=epic1.epic_id, title="Feature A")
            feature_b = Feature(epic_id=epic1.epic_id, title="Feature B")
            feature_c = Feature(epic_id=epic2.epic_id, title="Feature C")  # Different epic, same theme
            session.add_all([feature_a, feature_b, feature_c])
            session.commit()
            session.refresh(feature_a)

            target_feature_id = feature_a.feature_id

        context = fetch_feature_context(target_feature_id, engine=engine)

        assert context is not None
        assert "sibling_features" in context
        # Feature A should see B and C as siblings (same theme)
        assert "Feature B" in context["sibling_features"]
        assert "Feature C" in context["sibling_features"]
        assert "Feature A" not in context["sibling_features"]  # Exclude self


class TestSimplifiedProcessStoryInput:
    """Test that ProcessStoryInput can work with minimal required fields."""

    def test_minimal_input_only_requires_feature_id(self):
        """ProcessStoryInput should only require feature_id for basic construction."""
        from orchestrator_agent.agent_tools.story_pipeline.models import ProcessStoryInputMinimal

        # This should NOT raise - only feature_id is required
        input_data = ProcessStoryInputMinimal(feature_id=123)

        assert input_data.feature_id == 123
        # Defaults
        assert input_data.user_persona is None
        assert input_data.spec_version_id is None
        assert input_data.include_story_points is True

    def test_minimal_input_accepts_optional_overrides(self):
        """ProcessStoryInput should accept optional overrides for persona/spec."""
        from orchestrator_agent.agent_tools.story_pipeline.models import ProcessStoryInputMinimal

        input_data = ProcessStoryInputMinimal(
            feature_id=123,
            user_persona="admin",
            spec_version_id=456,
            include_story_points=False,
        )

        assert input_data.feature_id == 123
        assert input_data.user_persona == "admin"
        assert input_data.spec_version_id == 456
        assert input_data.include_story_points is False


class TestConvertMinimalToFullInput:
    """Test the conversion from minimal input to full ProcessStoryInput."""
    
    def test_converts_context_to_full_input(self):
        """Should merge context and minimal input into full ProcessStoryInput."""
        from orchestrator_agent.agent_tools.story_pipeline.single_story import _convert_minimal_to_full_input
        from orchestrator_agent.agent_tools.story_pipeline.models import ProcessStoryInputMinimal
        
        minimal = ProcessStoryInputMinimal(
            feature_id=42,
            user_persona="admin",
            include_story_points=False,
        )
        
        context = {
            "product_id": 1,
            "product_name": "Test Product",
            "product_vision": "Build great things",
            "theme_id": 10,
            "theme_name": "Core Infrastructure",
            "time_frame": "Now",
            "theme_justification": "Foundation work",
            "epic_id": 20,
            "epic_name": "Authentication",
            "feature_id": 42,
            "feature_title": "Login Flow",
            "sibling_features": ["Logout", "SSO"],
        }
        
        full_input = _convert_minimal_to_full_input(minimal, context)
        
        # From context
        assert full_input.product_id == 1
        assert full_input.product_name == "Test Product"
        assert full_input.theme == "Core Infrastructure"
        assert full_input.time_frame == "Now"
        assert full_input.feature_title == "Login Flow"
        assert full_input.sibling_features == ["Logout", "SSO"]
        
        # From minimal input (overrides)
        assert full_input.user_persona == "admin"
        assert full_input.include_story_points is False
