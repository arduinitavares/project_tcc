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
)
from agile_sqlmodel import Product, Theme, Epic, Feature


def test_process_story_input_requires_spec_version_id():
    """ProcessStoryInput should require spec_version_id."""
    with pytest.raises(ValidationError):
        ProcessStoryInput(
            product_id=1,
            product_name="Test Product",
            feature_id=1,
            feature_title="Test Feature",
            theme="Theme",
            epic="Epic",
        )


def test_process_batch_input_requires_spec_version_id():
    """ProcessBatchInput should require spec_version_id."""
    with pytest.raises(ValidationError):
        ProcessBatchInput(
            product_id=1,
            product_name="Test Product",
            product_vision="Vision",
            features=[],
        )


def test_save_stories_input_requires_spec_version_id():
    """SaveStoriesInput should require spec_version_id."""
    with pytest.raises(ValidationError):
        SaveStoriesInput(
            product_id=1,
            stories=[],
        )


@pytest.mark.asyncio
async def test_save_validated_stories_delegates_to_validation(monkeypatch, engine):
    """save_validated_stories should delegate to validate_story_with_spec_authority."""
    spec_tools.engine = engine
    import orchestrator_agent.agent_tools.story_pipeline.tools as story_tools
    monkeypatch.setattr(story_tools, "engine", engine)

    called = {"count": 0}

    def fake_validate(params, tool_context=None):
        called["count"] += 1
        return {"success": True, "passed": True}

    monkeypatch.setattr(
        "tools.spec_tools.validate_story_with_spec_authority",
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