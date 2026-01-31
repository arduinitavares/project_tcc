"""Tests for spec_version_id propagation through story pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, AsyncGenerator

import pytest
from sqlmodel import Session

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Feature,
    Product,
    SpecAuthorityAcceptance,
    SpecRegistry,
    Epic,
    Theme,
)
from orchestrator_agent.agent_tools.story_pipeline.tools import (
    ProcessStoryInput,
    process_single_story,
)
from utils.schemes import (
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)
import orchestrator_agent.agent_tools.story_pipeline.single_story as single_story_mod


def _make_compiled_artifact_json() -> str:
    invariant = Invariant(
        id="INV-0000000000000000",
        type=InvariantType.REQUIRED_FIELD,
        parameters=RequiredFieldParams(field_name="user_id"),
    )
    success = SpecAuthorityCompilationSuccess(
        scope_themes=["API"],
        invariants=[invariant],
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[],
        compiler_version="1.0.0",
        prompt_hash="a" * 64,
    )
    return SpecAuthorityCompilerOutput(root=success).model_dump_json()


def _create_compiled_authority(session: Session, product: Product) -> int:
    assert product.product_id is not None
    spec_version = SpecRegistry(
        product_id=product.product_id,
        spec_hash="spec_hash_123",
        content="Spec content",
        status="approved",
        approved_at=datetime.now(timezone.utc),
        approved_by="tester",
    )
    session.add(spec_version)
    session.commit()
    session.refresh(spec_version)

    assert spec_version.spec_version_id is not None
    compiled_authority = CompiledSpecAuthority(
        spec_version_id=spec_version.spec_version_id,
        compiler_version="1.0.0",
        prompt_hash="a" * 64,
        compiled_at=datetime.now(timezone.utc),
        compiled_artifact_json=_make_compiled_artifact_json(),
        scope_themes=json.dumps(["API"]),
        invariants=json.dumps([]),
        eligible_feature_ids=json.dumps([]),
        rejected_features=json.dumps([]),
        spec_gaps=json.dumps([]),
    )
    session.add(compiled_authority)
    session.commit()

    acceptance = SpecAuthorityAcceptance(
        product_id=product.product_id,
        spec_version_id=spec_version.spec_version_id,
        status="accepted",
        policy="human",
        decided_by="tester",
        compiler_version=compiled_authority.compiler_version,
        prompt_hash=compiled_authority.prompt_hash,
        spec_hash=spec_version.spec_hash,
    )
    session.add(acceptance)
    session.commit()

    return spec_version.spec_version_id


@pytest.mark.asyncio
async def test_spec_version_id_propagates_to_story_metadata(engine: Any) -> None:
    """Pipeline must override incorrect metadata spec_version_id with pinned ID."""
    single_story_mod.engine = engine

    with Session(engine) as session:
        product = Product(name="Spec Version Product", vision="Vision")
        session.add(product)
        session.commit()
        session.refresh(product)
        assert product.product_id is not None

        theme = Theme(title="Theme", product_id=product.product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)
        assert theme.theme_id is not None

        epic = Epic(title="Epic", theme_id=theme.theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)
        assert epic.epic_id is not None

        feature = Feature(title="Feature", epic_id=epic.epic_id)
        session.add(feature)
        session.commit()
        session.refresh(feature)
        assert feature.feature_id is not None

        spec_version_id = _create_compiled_authority(session, product)

        product_id = product.product_id
        product_name = product.name
        product_vision = product.vision
        feature_id = feature.feature_id
        feature_title = feature.title

    captured: Dict[str, Any] = {}

    class FakeSession:
        def __init__(self, state: Dict[str, Any]):
            self.state = state
            self.id = "session-1"

    class FakeSessionService:
        def __init__(self):
            self.session = None

        async def create_session(self, app_name: str, user_id: str, state: Dict[str, Any]):
            captured["state"] = state
            self.session = FakeSession(state)
            return self.session

        async def get_session(self, app_name: str, user_id: str, session_id: str):
            return self.session

    class FakeRunner:
        def __init__(self, agent: Any, app_name: str, session_service: FakeSessionService):
            self.session_service = session_service

        async def run_async(
            self, user_id: str, session_id: str, new_message: Any
        ) -> AsyncGenerator[Dict[str, Any], None]:
            assert self.session_service.session is not None
            self.session_service.session.state["story_draft"] = {
                "title": "Title",
                "description": "As a user, I want X so that Y.",
                "acceptance_criteria": "- A\n- B\n- C",
                "story_points": 3,
                "metadata": {"spec_version_id": 123},
            }
            yield {}

    original_session_service = single_story_mod.InMemorySessionService
    original_runner = single_story_mod.Runner
    single_story_mod.InMemorySessionService = FakeSessionService
    single_story_mod.Runner = FakeRunner
    try:
        result = await process_single_story(
            ProcessStoryInput(
                product_id=product_id,
                product_name=product_name,
                product_vision=product_vision,
                feature_id=feature_id,
                feature_title=feature_title,
                theme_id=None,
                epic_id=None,
                theme="Theme",
                epic="Epic",
                time_frame=None,
                theme_justification=None,
                sibling_features=None,
                user_persona="automation engineer",
                include_story_points=True,
                spec_version_id=spec_version_id,
                enable_story_refiner=False,
            )
        )
    finally:
        single_story_mod.InMemorySessionService = original_session_service
        single_story_mod.Runner = original_runner

    assert result["success"] is True
    story = result["story"]
    assert story["metadata"]["spec_version_id"] == spec_version_id
