# tests/test_alignment_checker_authority_pinning.py
"""Regression tests for alignment_checker authority pinning."""

import json
from pathlib import Path
from datetime import datetime, timezone

from typing import Any

import pytest
from sqlmodel import Session

from agile_sqlmodel import CompiledSpecAuthority
from orchestrator_agent.agent_tools.story_pipeline.alignment_checker import (
    derive_forbidden_capabilities_from_authority,
    validate_feature_alignment,
)


def _make_authority(invariants: list[str]) -> CompiledSpecAuthority:
    return CompiledSpecAuthority(
        spec_version_id=1,
        compiler_version="1.0.0",
        prompt_hash="test",
        compiled_at=datetime.now(timezone.utc),
        scope_themes=json.dumps(["theme"]),
        invariants=json.dumps(invariants),
        eligible_feature_ids=json.dumps([]),
        rejected_features=json.dumps([]),
        spec_gaps=json.dumps([]),
    )


def test_alignment_checker_requires_authority_or_invariants():
    """Calling without compiled_authority/invariants raises ValueError."""
    with pytest.raises(ValueError):
        validate_feature_alignment("Feature title")


def test_alignment_checker_uses_pinned_authority_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariants used must come from compiled authority."""
    invariants = ["FORBIDDEN_CAPABILITY:web"]
    authority = _make_authority(invariants)

    captured = {}

    def spy_derive(
        compiled_authority: CompiledSpecAuthority,
        invariants: list[str],
    ) -> list[Any]:
        captured["invariants"] = invariants
        return derive_forbidden_capabilities_from_authority(
            compiled_authority,
            invariants=invariants,
        )

    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.alignment_checker."
        "derive_forbidden_capabilities_from_authority",
        spy_derive,
    )

    validate_feature_alignment(
        "Web dashboard",
        compiled_authority=authority,
    )

    assert captured["invariants"] == invariants


def test_alignment_checker_does_not_use_vision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy vision-based helper should not be called."""
    def fail_if_called(_vision: str | None) -> None:
        raise AssertionError("Vision-based extraction should not be used")

    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.alignment_checker."
        "_extract_forbidden_capabilities_from_vision",
        fail_if_called,
    )

    validate_feature_alignment(
        "Web dashboard",
        _invariants=["FORBIDDEN_CAPABILITY:web"],
    )


@pytest.mark.asyncio
async def test_pipeline_alignment_requires_compiled_authority(
    engine: Any,
) -> None:
    """Pipeline entrypoints fail if authority is not compiled."""
    import orchestrator_agent.agent_tools.story_pipeline.tools as story_tools
    from orchestrator_agent.agent_tools.story_pipeline.tools import (
        ProcessStoryInput,
        process_single_story,
    )
    from agile_sqlmodel import Product, Theme, Epic, Feature
    import tools.spec_tools as spec_tools
    from tools.spec_tools import register_spec_version, approve_spec_version

    story_tools.engine = engine
    spec_tools.engine = engine

    with Session(engine) as session:
        product = Product(name="Test Product", vision="Test")
        session.add(product)
        session.commit()
        session.refresh(product)
        assert product.product_id is not None
        product_id = int(product.product_id)
        product_name = product.name
        product_vision = product.vision

        theme = Theme(title="Theme", product_id=product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)
        assert theme.theme_id is not None
        theme_id = int(theme.theme_id)

        epic = Epic(title="Epic", theme_id=theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)
        assert epic.epic_id is not None
        epic_id = int(epic.epic_id)

        feature = Feature(title="Feature", epic_id=epic_id)
        session.add(feature)
        session.commit()
        session.refresh(feature)
        assert feature.feature_id is not None
        feature_id = int(feature.feature_id)

    # Register and approve spec but DO NOT compile
    reg_result = register_spec_version(
        {"product_id": product_id, "content": "Spec content"},
        tool_context=None,
    )
    spec_version_id = reg_result["spec_version_id"]
    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "tester"},
        tool_context=None,
    )

    result = await process_single_story(
        ProcessStoryInput(
            product_id=product_id,
            product_name=product_name,
            product_vision=product_vision,
            spec_version_id=spec_version_id,
            feature_id=feature_id,
            feature_title=feature.title,
            theme_id=None,
            epic_id=None,
            theme="Theme",
            epic="Epic",
            time_frame=None,
            theme_justification=None,
            sibling_features=None,
            user_persona="user",
            include_story_points=True,
            enable_story_refiner=False,
        )
    )

    assert result["success"] is False
    assert "not compiled" in result["error"].lower()


def test_no_latest_spec_fallback_anywhere():
    """Ensure story pipeline tools do not reference latest spec fallbacks."""
    path = Path(__file__).resolve().parents[1] / "orchestrator_agent" / "agent_tools" / "story_pipeline" / "tools.py"
    with path.open("r", encoding="utf-8") as handle:
        content = handle.read().lower()

    assert "latest approved" not in content
    assert "technical_spec is none" not in content
    assert "product.technical_spec" not in content