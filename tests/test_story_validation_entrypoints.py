# tests/test_story_validation_entrypoints.py
"""
Tests to ensure public validation entry points require spec_version_id
and delegate to validate_story_with_spec_authority().
"""

import pytest
from pydantic import ValidationError
from sqlmodel import Session

import tools.spec_tools as spec_tools
from orchestrator_agent.agent_tools.story_pipeline.tools import (
    ProcessStoryInput,
    ProcessBatchInput,
    SaveStoriesInput,
    save_validated_stories,
    process_story_batch,
)
from tools.story_query_tools import FeatureForStory
from agile_sqlmodel import Product, Theme, Epic, Feature


def test_process_story_input_allows_missing_spec_version_id():
    """ProcessStoryInput should allow missing spec_version_id (authority gate handles it)."""
    input_data = ProcessStoryInput(
        product_id=1,
        product_name="Test Product",
        feature_id=1,
        feature_title="Test Feature",
        theme_id=1,
        epic_id=1,
        theme="Theme",
        epic="Epic",
        spec_version_id=None,
    )
    assert input_data.spec_version_id is None


def test_process_batch_input_allows_missing_spec_version_id():
    """ProcessBatchInput should allow missing spec_version_id (authority gate handles it)."""
    batch_input = ProcessBatchInput(
        product_id=1,
        product_name="Test Product",
        product_vision="Vision",
        features=[],
        spec_version_id=None,
    )
    assert batch_input.spec_version_id is None


def test_save_stories_input_requires_spec_version_id():
    """SaveStoriesInput should require spec_version_id."""
    with pytest.raises(ValidationError):
        SaveStoriesInput(
            product_id=1,
            # stories is now optional (defaults to None for session state fallback)
        )


def test_save_stories_input_allows_optional_stories():
    """SaveStoriesInput should allow omitting stories (will use session state fallback)."""
    # This should NOT raise - stories is optional
    input_obj = SaveStoriesInput(
        product_id=1,
        spec_version_id=1,
    )
    assert input_obj.stories is None


@pytest.mark.asyncio
async def test_process_story_batch_injects_spec_version_id(monkeypatch, engine):
    """process_story_batch should inject spec_version_id from the authority gate."""
    import orchestrator_agent.agent_tools.story_pipeline.batch as batch_mod

    # Mock get_engine to return test engine
    monkeypatch.setattr(batch_mod, "get_engine", lambda: engine)

    captured = {}

    async def fake_process_single_story(story_input, output_callback=None, tool_context=None):
        captured["spec_version_id"] = story_input.spec_version_id
        return {"success": True, "story": None}

    def fake_load_compiled_authority(*_args, **_kwargs):
        return None, None, "spec text"

    monkeypatch.setattr(batch_mod, "process_single_story", fake_process_single_story)
    monkeypatch.setattr(batch_mod, "load_compiled_authority", fake_load_compiled_authority)
    monkeypatch.setattr(batch_mod, "ensure_accepted_spec_authority", lambda *_args, **_kwargs: 42)

    feature = FeatureForStory(
        feature_id=1,
        feature_title="Feature",
        theme_id=1,
        epic_id=1,
        theme="Theme",
        epic="Epic",
    )

    batch_input = ProcessBatchInput(
        product_id=1,
        product_name="Test Product",
        product_vision="Vision",
        features=[feature],
        spec_version_id=None,
        spec_content="Spec v1",
    )

    result = await process_story_batch(batch_input)

    assert result["success"] is True
    assert captured["spec_version_id"] == 42


@pytest.mark.asyncio
async def test_process_story_batch_uses_pending_spec_from_context(monkeypatch, engine):
    """process_story_batch should pass pending spec from tool_context when needed."""
    import orchestrator_agent.agent_tools.story_pipeline.batch as batch_mod

    # Mock get_engine to return test engine
    monkeypatch.setattr(batch_mod, "get_engine", lambda: engine)

    captured = {}

    def fake_ensure_accepted_spec_authority(*_args, **kwargs):
        captured["spec_content"] = kwargs.get("spec_content")
        captured["content_ref"] = kwargs.get("content_ref")
        return 7

    def fake_load_compiled_authority(*_args, **_kwargs):
        return None, None, "spec text"

    async def fake_process_single_story(story_input, output_callback=None, tool_context=None):
        return {"success": True, "story": None}

    monkeypatch.setattr(batch_mod, "ensure_accepted_spec_authority", fake_ensure_accepted_spec_authority)
    monkeypatch.setattr(batch_mod, "load_compiled_authority", fake_load_compiled_authority)
    monkeypatch.setattr(batch_mod, "process_single_story", fake_process_single_story)

    feature = FeatureForStory(
        feature_id=1,
        feature_title="Feature",
        theme_id=1,
        epic_id=1,
        theme="Theme",
        epic="Epic",
    )

    batch_input = ProcessBatchInput(
        product_id=1,
        product_name="Test Product",
        product_vision="Vision",
        features=[feature],
        spec_version_id=None,
    )

    class MockToolContext:
        def __init__(self, state):
            self.state = state

    context = MockToolContext(state={"pending_spec_path": "test_specs\\genai_spec.md"})

    result = await process_story_batch(batch_input, tool_context=context)

    assert result["success"] is True
    assert captured["content_ref"] == "test_specs\\genai_spec.md"


@pytest.mark.asyncio
async def test_process_story_batch_treats_rejected_as_failure(monkeypatch, engine):
    """process_story_batch should not validate stories rejected by constraint checks."""
    import orchestrator_agent.agent_tools.story_pipeline.batch as batch_mod

    # Mock get_engine to return test engine
    monkeypatch.setattr(batch_mod, "get_engine", lambda: engine)

    captured = {}

    async def fake_process_single_story(story_input, output_callback=None, tool_context=None):
        captured["time_frame"] = story_input.time_frame
        return {
            "success": True,
            "is_valid": True,
            "rejected": True,
            "alignment_issues": [
                "Constraint check: IoU >= 0.7 violates your instruction",
            ],
            "story": {
                "title": "IoU gating",
                "description": "As a user, I want IoU threshold gating.",
                "acceptance_criteria": "- IoU >= 0.7",
                "story_points": 3,
            },
        }

    def fake_load_compiled_authority(*_args, **_kwargs):
        return None, None, "spec text"

    monkeypatch.setattr(batch_mod, "process_single_story", fake_process_single_story)
    monkeypatch.setattr(batch_mod, "load_compiled_authority", fake_load_compiled_authority)
    monkeypatch.setattr(batch_mod, "ensure_accepted_spec_authority", lambda *_a, **_k: 1)

    feature = FeatureForStory(
        feature_id=1,
        feature_title="IoU feature",
        theme_id=1,
        epic_id=1,
        theme="Theme",
        epic="Epic",
        time_frame="Now",
    )

    batch_input = ProcessBatchInput(
        product_id=1,
        product_name="Test Product",
        product_vision="Vision",
        features=[feature],
        spec_version_id=None,
        spec_content="Spec v1",
    )

    result = await process_story_batch(batch_input)

    assert captured["time_frame"] == "Now"
    assert result["failed_count"] == 1
    assert result["validated_count"] == 0
    assert result["validated_stories"] == []


@pytest.mark.asyncio
async def test_save_validated_stories_delegates_to_validation(monkeypatch, engine):
    """save_validated_stories should delegate to validate_story_with_spec_authority."""
    import orchestrator_agent.agent_tools.story_pipeline.save as save_mod
    # Mock get_engine to return test engine
    monkeypatch.setattr(save_mod, "get_engine", lambda: engine)

    called = {"count": 0}

    def fake_validate(params, tool_context=None):
        called["count"] += 1
        return {"success": True, "passed": True}

    monkeypatch.setattr(
        "tools.spec_tools.validate_story_with_spec_authority",
        fake_validate,
    )
    # Also patch where it's imported in save module
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.save.validate_story_with_spec_authority",
        fake_validate,
    )

    # Minimal DB setup for story save
    with Session(engine) as session:
        product = Product(name="Test Product", vision="Vision")
        session.add(product)
        session.commit()
        session.refresh(product)
        product_id = product.product_id

        theme = Theme(title="Theme", product_id=product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)

        epic = Epic(title="Epic", theme_id=theme.theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)

        feature = Feature(title="Feature", epic_id=epic.epic_id)
        session.add(feature)
        session.commit()
        session.refresh(feature)
        feature_id = feature.feature_id

    save_input = SaveStoriesInput(
        product_id=product_id,
        spec_version_id=1,
        stories=[
            {
                "feature_id": feature_id,
                "title": "Story",
                "description": "As a user, I want...",
                "acceptance_criteria": "- AC",
                "story_points": 1,
            }
        ],
    )

    result = await save_validated_stories(save_input)

    assert result["success"] is True
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_save_validated_stories_falls_back_to_session_state(monkeypatch, engine):
    """save_validated_stories should retrieve stories from session state if not provided."""
    import orchestrator_agent.agent_tools.story_pipeline.save as save_mod
    # Mock get_engine to return test engine
    monkeypatch.setattr(save_mod, "get_engine", lambda: engine)
    
    called = {"count": 0}

    def fake_validate(params, tool_context=None):
        called["count"] += 1
        return {"success": True, "passed": True}

    # Patch at the source module where it's imported from
    monkeypatch.setattr(
        "tools.spec_tools.validate_story_with_spec_authority",
        fake_validate,
    )
    # Also patch where it's imported in save module
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.save.validate_story_with_spec_authority",
        fake_validate,
    )

    with Session(engine) as session:
        product = Product(name="Test Product Fallback", vision="Vision")
        session.add(product)
        session.commit()
        session.refresh(product)
        product_id = product.product_id

        theme = Theme(title="Theme", product_id=product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)

        epic = Epic(title="Epic", theme_id=theme.theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)

        feature = Feature(title="Feature", epic_id=epic.epic_id)
        session.add(feature)
        session.commit()
        session.refresh(feature)
        feature_id = feature.feature_id

    # Create a mock tool_context with pending_validated_stories in state
    class MockState(dict):
        pass
    
    class MockToolContext:
        def __init__(self):
            self.state = MockState()
    
    mock_context = MockToolContext()
    mock_context.state["pending_validated_stories"] = [
        {
            "feature_id": feature_id,
            "title": "Valid story from state",
            "description": "As a user, I want to test the session fallback mechanism",
            "acceptance_criteria": "- Story is retrieved from session state\\n- Story is saved successfully",
            "story_points": 2,
        }
    ]

    # Call without providing stories - should use session state fallback
    save_input = SaveStoriesInput(
        product_id=product_id,
        spec_version_id=1,
        # stories is omitted - should use session state
    )

    result = await save_validated_stories(save_input, tool_context=mock_context)

    assert result["success"] is True
    assert result["saved_count"] == 1
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_save_validated_stories_errors_without_stories_or_state():
    """save_validated_stories should return error if no stories and no session state."""
    save_input = SaveStoriesInput(
        product_id=1,
        spec_version_id=1,
        # stories is omitted, no tool_context provided
    )

    result = await save_validated_stories(save_input, tool_context=None)

    assert result["success"] is False
    assert "No stories provided" in result["error"]