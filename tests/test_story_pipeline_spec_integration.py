"""Integration test for spec-respecting story generation (spec validator + refiner)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

import agile_sqlmodel
from agile_sqlmodel import (
    CompiledSpecAuthority,
    Epic,
    Product,
    SpecAuthorityAcceptance,
    SpecRegistry,
    Theme,
)
from orchestrator_agent.agent_tools.story_pipeline.tools import (
    ProcessStoryInput,
    process_single_story,
)
from utils.schemes import (
    ForbiddenCapabilityParams,
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)


PROMPT_HASH = "a" * 64
COMPILER_VERSION = "1.0.0"


def _build_compiled_artifact_json() -> str:
    required_field = Invariant(
        id="INV-0000000000000001",
        type=InvariantType.REQUIRED_FIELD,
        parameters=RequiredFieldParams(field_name="user_id"),
    )
    forbidden_capability = Invariant(
        id="INV-0000000000000002",
        type=InvariantType.FORBIDDEN_CAPABILITY,
        parameters=ForbiddenCapabilityParams(capability="OAuth1 authentication"),
    )
    success = SpecAuthorityCompilationSuccess(
        scope_themes=["payload_validation", "authentication_constraints"],
        domain="api",
        invariants=[required_field, forbidden_capability],
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[],
        compiler_version=COMPILER_VERSION,
        prompt_hash=PROMPT_HASH,
    )
    return SpecAuthorityCompilerOutput(root=success).model_dump_json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_story_pipeline_respects_spec_invariants(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end check that story output honors required/forbidden spec rules."""
    monkeypatch.setenv("ALLOW_PROD_DB_IN_TEST", "1")
    monkeypatch.setattr(agile_sqlmodel, "_production_engine", engine)
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.steps.alignment_checker."
        "model_config.get_story_pipeline_negation_tolerance",
        lambda: True,
    )
    with Session(engine) as session:
        product = Product(name="Spec Compliance Product", vision="Spec compliance harness")
        session.add(product)
        session.commit()
        session.refresh(product)

        assert product.product_id is not None
        theme = Theme(title="Core", product_id=product.product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)

        assert theme.theme_id is not None
        epic = Epic(title="User Data", theme_id=theme.theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)

        spec_registry = SpecRegistry(
            product_id=product.product_id,
            spec_hash="spec_hash_001",
            content=(
                "# Spec\n\n## Requirements\n"
                "- The payload must include user_id.\n"
                "- The system must not use OAuth1 authentication."
            ),
            status="approved",
            approved_at=datetime.now(timezone.utc),
            approved_by="tester",
        )
        session.add(spec_registry)
        session.commit()
        session.refresh(spec_registry)

        assert spec_registry.spec_version_id is not None
        compiled_authority = CompiledSpecAuthority(
            spec_version_id=spec_registry.spec_version_id,
            compiler_version=COMPILER_VERSION,
            prompt_hash=PROMPT_HASH,
            compiled_at=datetime.now(timezone.utc),
            compiled_artifact_json=_build_compiled_artifact_json(),
            scope_themes="[\"payload_validation\", \"authentication_constraints\"]",
            invariants="[]",
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
        )
        session.add(compiled_authority)
        session.commit()

        acceptance = SpecAuthorityAcceptance(
            product_id=product.product_id,
            spec_version_id=spec_registry.spec_version_id,
            status="accepted",
            policy="human",
            decided_by="tester",
            compiler_version=COMPILER_VERSION,
            prompt_hash=PROMPT_HASH,
            spec_hash=spec_registry.spec_hash,
        )
        session.add(acceptance)
        session.commit()

        product_id = product.product_id
        product_name = product.name
        product_vision = product.vision
        theme_id = theme.theme_id
        theme_title = theme.title
        epic_id = epic.epic_id
        epic_title = epic.title
        spec_version_id = spec_registry.spec_version_id

        assert theme_id is not None
        assert epic_id is not None
        assert spec_version_id is not None

    result = await process_single_story(
        ProcessStoryInput(
            product_id=product_id,
            product_name=product_name,
            product_vision=product_vision,
            feature_id=101,
            feature_title="Capture user_id in payload",
            theme_id=theme_id,
            epic_id=epic_id,
            theme=theme_title,
            epic=epic_title,
            time_frame=None,
            theme_justification=None,
            sibling_features=None,
            user_persona="automation engineer",
            include_story_points=True,
            spec_version_id=spec_version_id,
            enable_story_refiner=True,
            enable_spec_validator=True,
            pass_raw_spec_text=True,
        )
    )

    assert result["success"] is True
    assert result["rejected"] is False
    assert result["alignment_issues"] == []

    story = result["story"]
    story_text = (
        f"{story.get('title', '')} {story.get('description', '')} {story.get('acceptance_criteria', '')}"
    ).lower()

    assert "user_id" in story_text, "Story must include required field: user_id"
