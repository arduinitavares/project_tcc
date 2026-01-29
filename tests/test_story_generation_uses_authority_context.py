"""Tests for compiled authority generation context usage in story drafting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, AsyncGenerator

import pytest
from pytest import MonkeyPatch
from sqlalchemy.engine import Engine
from sqlmodel import Session

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Product,
    SpecAuthorityAcceptance,
    SpecRegistry,
)
from orchestrator_agent.agent_tools.story_pipeline.story_generation_context import (
    build_generation_context,
)
from utils.schemes import (
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)


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


def test_build_generation_context_renders_invariants() -> None:
    """Generation context should include canonical invariant strings."""
    compiled_authority = CompiledSpecAuthority(
        spec_version_id=1,
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

    context = build_generation_context(
        compiled_authority=compiled_authority,
        spec_version_id=1,
        spec_hash="spec_hash_123",
    )

    assert context["spec_version_id"] == 1
    assert "REQUIRED_FIELD:user_id" in context["invariants"]
    assert context["scope_themes"] == ["API"]
    assert context["spec_hash"] == "spec_hash_123"


@pytest.mark.asyncio
async def test_draft_payload_includes_authority_context(
    engine: Engine, monkeypatch: MonkeyPatch
) -> None:
    """Draft agent input state should include authority_context and spec_version_id."""
    import orchestrator_agent.agent_tools.story_pipeline.tools as story_tools
    from orchestrator_agent.agent_tools.story_pipeline.tools import (
        ProcessStoryInput,
        process_single_story,
    )

    story_tools.engine = engine

    with Session(engine) as session:
        product = Product(name="Test Product", vision="Vision")
        session.add(product)
        session.commit()
        session.refresh(product)

        assert product.product_id is not None

        product_id = product.product_id
        product_name = product.name
        product_vision = product.vision

        spec_version_id = _create_compiled_authority(session, product)

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
                "metadata": {"spec_version_id": spec_version_id},
            }
            yield {}

    monkeypatch.setattr(story_tools, "InMemorySessionService", FakeSessionService)
    monkeypatch.setattr(story_tools, "Runner", FakeRunner)

    result = await process_single_story(
        ProcessStoryInput(
            product_id=product_id,
            product_name=product_name,
            product_vision=product_vision,
            feature_id=101,
            feature_title="Feature",
            theme_id=None,
            epic_id=None,
            theme="Theme",
            epic="Epic",
            time_frame=None,
            theme_justification=None,
            sibling_features=None,
            user_persona="user",
            include_story_points=True,
            spec_version_id=spec_version_id,
            enable_story_refiner=False,
        )
    )

    assert result["success"] is True
    state = captured["state"]
    assert "authority_context" in state
    assert "spec_version_id" in state

    authority_context = json.loads(state["authority_context"])
    assert authority_context["spec_version_id"] == spec_version_id
