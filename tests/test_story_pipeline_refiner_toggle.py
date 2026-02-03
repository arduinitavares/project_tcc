"""Tests for story refiner toggle in pipeline entrypoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, AsyncGenerator

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
from orchestrator_agent.agent_tools.story_pipeline.pipeline import story_validation_loop
from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import (
    story_draft_agent,
)


def _seed_compiled_authority(session: Session, product: Product) -> int:
    assert product.product_id is not None
    spec_version = SpecRegistry(
        product_id=product.product_id,
        spec_hash="spec_hash_abc",
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
        compiled_artifact_json=None,
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
async def test_refiner_disabled_skips_loop(
    engine: Engine, monkeypatch: MonkeyPatch
) -> None:
    """When enable_story_refiner=False, only draft agent should run."""
    import orchestrator_agent.agent_tools.story_pipeline.single_story as single_story_mod
    from orchestrator_agent.agent_tools.story_pipeline.tools import (
        ProcessStoryInput,
        process_single_story,
    )

    single_story_mod.engine = engine

    with Session(engine) as session:
        product = Product(name="Test Product", vision="Vision")
        session.add(product)
        session.commit()
        session.refresh(product)

        assert product.product_id is not None

        product_id = product.product_id
        product_name = product.name
        product_vision = product.vision

        spec_version_id = _seed_compiled_authority(session, product)

    recorded_agents: List[Any] = []

    class FakeSession:
        def __init__(self, state: Dict[str, Any]):
            self.state = state
            self.id = "session-1"

    class FakeSessionService:
        def __init__(self):
            self.session = None

        async def create_session(self, app_name: str, user_id: str, state: Dict[str, Any]):
            self.session = FakeSession(state)
            return self.session

        async def get_session(self, app_name: str, user_id: str, session_id: str):
            return self.session

    class FakeRunner:
        def __init__(self, agent: Any, app_name: str, session_service: FakeSessionService):
            recorded_agents.append(agent)
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
            yield type("Event", (), {"content": None, "author": None})()

    monkeypatch.setattr(single_story_mod, "InMemorySessionService", FakeSessionService)
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.steps.execution.Runner",
        FakeRunner,
    )

    result = await process_single_story(
        ProcessStoryInput(
            product_id=product_id,
            product_name=product_name,
            product_vision=product_vision,
            feature_id=101,
            feature_title="Feature",
            theme_id=1,
            epic_id=1,
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
    assert any(getattr(agent, "name", "") == "SelfHealing_StoryDraftAgent" for agent in recorded_agents)
    assert story_draft_agent not in recorded_agents
    assert story_validation_loop not in recorded_agents


@pytest.mark.asyncio
async def test_refiner_enabled_invokes_loop(
    engine: Engine, monkeypatch: MonkeyPatch
) -> None:
    """When enable_story_refiner=True, loop agent should run once."""
    import orchestrator_agent.agent_tools.story_pipeline.single_story as single_story_mod
    from orchestrator_agent.agent_tools.story_pipeline.tools import (
        ProcessStoryInput,
        process_single_story,
    )

    single_story_mod.engine = engine

    with Session(engine) as session:
        product = Product(name="Test Product", vision="Vision")
        session.add(product)
        session.commit()
        session.refresh(product)

        assert product.product_id is not None

        product_id = product.product_id
        product_name = product.name
        product_vision = product.vision

        spec_version_id = _seed_compiled_authority(session, product)

    recorded_agents: List[Any] = []

    class FakeSession:
        def __init__(self, state: Dict[str, Any]):
            self.state = state
            self.id = "session-1"

    class FakeSessionService:
        def __init__(self):
            self.session = None

        async def create_session(self, app_name: str, user_id: str, state: Dict[str, Any]):
            self.session = FakeSession(state)
            return self.session

        async def get_session(self, app_name: str, user_id: str, session_id: str):
            return self.session

    class FakeRunner:
        def __init__(self, agent: Any, app_name: str, session_service: FakeSessionService):
            recorded_agents.append(agent)
            self.session_service = session_service

        async def run_async(
            self, user_id: str, session_id: str, new_message: Any
        ) -> AsyncGenerator[Dict[str, Any], None]:
            assert self.session_service.session is not None
            self.session_service.session.state["refinement_result"] = {
                "refined_story": {
                    "title": "Title",
                    "description": "As a user, I want X so that Y.",
                    "acceptance_criteria": "- A\n- B\n- C",
                    "story_points": 3,
                    "metadata": {"spec_version_id": spec_version_id},
                },
                "is_valid": True,
                "refinement_applied": False,
                "refinement_notes": "No changes needed.",
            }
            yield type("Event", (), {"content": None, "author": None})()

    monkeypatch.setattr(single_story_mod, "InMemorySessionService", FakeSessionService)
    monkeypatch.setattr(
        "orchestrator_agent.agent_tools.story_pipeline.steps.execution.Runner",
        FakeRunner,
    )

    result = await process_single_story(
        ProcessStoryInput(
            product_id=product_id,
            product_name=product_name,
            product_vision=product_vision,
            feature_id=101,
            feature_title="Feature",
            theme_id=1,
            epic_id=1,
            theme="Theme",
            epic="Epic",
            time_frame=None,
            theme_justification=None,
            sibling_features=None,
            user_persona="user",
            include_story_points=True,
            spec_version_id=spec_version_id,
            enable_story_refiner=True,
        )
    )

    assert result["success"] is True
    assert recorded_agents.count(story_validation_loop) == 1


@pytest.mark.asyncio
async def test_missing_spec_version_id_fails_fast() -> None:
    """Pipeline should fail fast when spec_version_id is missing/zero."""
    from orchestrator_agent.agent_tools.story_pipeline.tools import (
        ProcessStoryInput,
        process_single_story,
    )

    result = await process_single_story(
        ProcessStoryInput(
            product_id=1,
            product_name="Test Product",
            product_vision=None,
            feature_id=101,
            feature_title="Feature",
            theme_id=1,
            epic_id=1,
            theme="Theme",
            epic="Epic",
            time_frame=None,
            theme_justification=None,
            sibling_features=None,
            user_persona="user",
            include_story_points=True,
            spec_version_id=0,
            enable_story_refiner=False,
        )
    )

    assert result["success"] is False
    assert "spec_version_id" in result["error"].lower()
